"""Thin SuperDocs client covering the four calls this build needs.

upload, chat, approve, export. Nothing else. Written against the live REST API
at https://api.superdocs.app with the shapes I verified by hand, which are
recorded in PROGRESS.md.
"""

import json
import os
import time
import urllib.error
import urllib.request
import uuid

BASE_URL = os.environ.get("SUPERDOCS_BASE_URL", "https://api.superdocs.app")

# A chat job on a multi-letter document can sit without visible progress for
# minutes. Silence is normal processing here, so the poller waits it out instead
# of treating a quiet job as a failure.
POLL_INTERVAL_SECONDS = 5
POLL_TIMEOUT_SECONDS = 1800


class SuperDocsError(Exception):
    pass


class SuperDocs(object):
    def __init__(self, api_key=None, log=None):
        self.api_key = api_key or os.environ.get("SUPERDOCS_API_KEY")
        if not self.api_key:
            raise SuperDocsError(
                "No API key. Set SUPERDOCS_API_KEY, or run with --offline to skip the API stage.")
        self.log = log or (lambda message: None)

    def _request(self, method, path, body=None, headers=None, raw_body=None, want_bytes=False):
        request_headers = {"Authorization": "Bearer " + self.api_key}
        if headers:
            request_headers.update(headers)
        data = raw_body
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(BASE_URL + path, data=data,
                                        headers=request_headers, method=method)
        try:
            response = urllib.request.urlopen(request, timeout=600)
            payload = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:600]
            raise SuperDocsError("{0} {1} returned {2}: {3}".format(
                method, path, error.code, detail))
        if want_bytes:
            return payload
        return json.loads(payload.decode("utf-8"))

    def upload_document(self, session_id, filename, html):
        """Call 1 of 4. Upload the letter template as the session document."""
        boundary = uuid.uuid4().hex
        parts = []
        for name, value in (("session_id", session_id), ("open_mode", "replace")):
            parts.append(("--{0}\r\nContent-Disposition: form-data; name=\"{1}\"\r\n\r\n{2}\r\n"
                          .format(boundary, name, value)).encode("utf-8"))
        parts.append(("--{0}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{1}\""
                      "\r\nContent-Type: text/html\r\n\r\n".format(boundary, filename)).encode("utf-8"))
        parts.append(html.encode("utf-8") + b"\r\n")
        parts.append(("--{0}--\r\n".format(boundary)).encode("utf-8"))
        self.log("upload: sending {0} ({1} bytes of html)".format(filename, len(html)))
        return self._request("POST", "/v1/documents/upload", raw_body=b"".join(parts),
                             headers={"Content-Type": "multipart/form-data; boundary=" + boundary})

    def start_chat(self, session_id, message, model_tier="core", thinking_depth="balanced"):
        """Call 2 of 4. Ask for the figure insertion and stop before it is applied.

        approval_mode ask_every_time means the edit is only proposed, so the
        proposed wording can be verified against the approved block before
        anything is accepted.
        """
        started = self._request("POST", "/v1/chat/async", {
            "session_id": session_id,
            "message": message,
            "model_tier": model_tier,
            "thinking_depth": thinking_depth,
            "approval_mode": "ask_every_time",
        })
        job_id = started.get("job_id")
        if not job_id:
            raise SuperDocsError("chat/async did not return a job_id: " + json.dumps(started)[:300])
        self.log("chat: job {0} queued, waiting for proposed changes".format(job_id))
        return job_id

    def wait_for_pause(self, job_id):
        """Wait until the job either offers changes to approve or finishes.

        A long document is proposed in rounds: the job pauses at
        awaiting_approval, and only resumes once the changes in that round have
        been answered, so the caller has to keep pumping this until completed.
        """
        job = self._wait_for_job(job_id)
        return job.get("status"), self._pending_changes(job)

    def _wait_for_job(self, job_id):
        deadline = time.time() + POLL_TIMEOUT_SECONDS
        last_status = None
        while time.time() < deadline:
            job = self._request("GET", "/v1/jobs/" + job_id)
            status = job.get("status")
            if status != last_status:
                self.log("chat: job status {0}".format(status))
                last_status = status
            if status in ("awaiting_approval", "completed"):
                return job
            if status in ("failed", "cancelled"):
                raise SuperDocsError("job {0} ended as {1}: {2}".format(
                    job_id, status, str(job.get("error"))[:300]))
            time.sleep(POLL_INTERVAL_SECONDS)
        raise SuperDocsError("job {0} did not finish within {1} seconds".format(
            job_id, POLL_TIMEOUT_SECONDS))

    @staticmethod
    def _pending_changes(job):
        """Read metadata.pending_changes, which may arrive JSON encoded twice.

        On my account it came back as a real list, but the documented behaviour is
        a JSON string, so both are handled rather than guessed at.
        """
        changes = (job.get("metadata") or {}).get("pending_changes")
        for _ in range(2):
            if isinstance(changes, str):
                changes = json.loads(changes)
        if changes is None:
            return []
        if isinstance(changes, dict):
            changes = changes.get("changes") or []
        return changes

    def approve(self, session_id, job_id, change_id, approved):
        """Call 3 of 4. Accept or deny one proposed change."""
        return self._request("POST", "/v1/chat/{0}/approve".format(session_id), {
            "job_id": job_id,
            "change_id": change_id,
            "approved": bool(approved),
        })

    def export(self, session_id, export_format, filename):
        """Call 4 of 4. Export the finished document. Exports cost no operations."""
        return self._request("POST", "/v1/documents/export", {
            "session_id": session_id,
            "format": export_format,
            "options": {"filename": filename},
        }, want_bytes=True)
