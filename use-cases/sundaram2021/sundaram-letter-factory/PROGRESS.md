# Build log

This is the running log of what I decided while building the letter factory, and why. I kept it as I went rather than writing it up afterwards, so the awkward parts are in here too.

## Decisions I made on my own

**Folder path.** The brief told me to build in `use-cases/sundaram-letter-factory/`, but `CONTRIBUTING.md` in this repo says the path is `use-cases/<your-github-username>/<project-name>/`. I followed CONTRIBUTING, since that is the repo's own rule, and kept the project name I was given. So the work lives at `use-cases/sundaram2021/sundaram-letter-factory/`.

**No AI anywhere near the wording or the figures.** The brief allows an AI step to help select or insert content. I decided against it. Every figure comes from the formula in `data/rules.json`, and every letter is approved wording with placeholder tokens literally substituted. That way "the AI never rewrites approved wording" is a property of the design, not a promise I have to trust a model to keep.

The one AI step I did add is a reviewer, in `ai_review.py`, using a Haiku class model. It reads a proposed change and says MATCH or DRIFT. It is off by default, it is advisory only, and the deterministic byte comparison in `run.py` is what actually decides whether a change gets approved. I could not run it live from the machine I built on, because outbound calls to the Anthropic API were blocked there, so I have exercised its failure path (missing key, unreachable endpoint) but not a successful call. I would rather say that plainly than imply I tested something I did not.

**How I enforce "never paraphrased".** I upload the approved wording with placeholder tokens still in it, ask SuperDocs to substitute the values, and then compare what it proposes against the text I assembled locally, character for character after stripping HTML tags and collapsing whitespace. A change is approved only on an exact match. Anything else is denied and the record is held with the expected and received text both printed. This means the SuperDocs chat call genuinely does the insertion, and a model changing a single word cannot reach a customer.

I compare on visible text rather than raw HTML because the editor can legitimately return equivalent markup. Every visible character still has to match.

**Money in integer cents, Decimal throughout.** No floats anywhere in the arithmetic. Rounding is half up to the cent, stated once in the data file.

**Placeholder tokens are namespaced per customer.** In a batch, `{{customer_name}}` would appear once per letter with a different correct value each time. So the uploaded template carries `{{CUS-1001.customer_name}}` instead. Ambiguity disappears and each token maps to exactly one value.

## What the live API actually does, as opposed to what I assumed

I probed the API by hand before writing the client. Notes worth keeping:

- `POST /v1/chat/{session_id}/approve` needs `job_id`, `change_id` and `approved`. I first tried `change_id` plus `action: accept`, which is a 422.
- Approval is not one shot. The job pauses at `awaiting_approval`, and it only resumes once the changes in that round are answered. So the client has to keep pumping: wait, verify, approve, wait again, until the job reports `completed`. My first working version approved one round and stopped, which left most sections unfilled.
- The editor proposes changes to sections that contain no placeholder at all, effectively re-proposing them unchanged. That is harmless here and actually useful: I verify those too, so drift in a section I was not even editing would be caught and denied.
- On `core` tier a two letter batch stopped part way through, filling one section and declaring itself complete. On `pro` it completed a full batch in a single turn every time. So the tier is `pro`, and the instruction ends with an explicit completion condition ("the document is not finished until no token remains"). Both changes mattered.
- The documented gotcha is that `metadata.pending_changes` arrives as a JSON encoded string needing a second parse. On my account it came back as a real JSON list. I parse defensively for both rather than assuming either.
- Long silent stretches are normal. The poller waits up to 30 minutes per job and never treats quiet as failure. There is no retry that assumes a stall is an error.

## Batching and operation cost

One operation covers up to 25 sections of targeted edits. I originally packed batches by counting only the sections holding placeholders, but since the editor proposes changes across every section, I now count every section a letter contributes plus its separator. That works out to two letters per batch, so a full 22 letter run costs about 11 operations. Exports are free, so I export every batch. A customer is never sent through twice: records are deduplicated by `customer_id`, and the follow up turn only ever names sections that are still unfilled.

## Proving the no code change claim

I built and tested the pipeline with California and Texas only, committed that, and then added New York purely as data: a jurisdiction entry in `rules.json`, four wording blocks, and four customer records. No `.py` file was touched. The git history shows this as its own commit, so the claim is checkable rather than asserted.

## What I would do next

- The batch export is one DOCX containing two letters with an internal separator heading. A real ops team would want one file per customer from SuperDocs itself. I write per customer HTML locally, but the DOCX export is per batch.
- The AI reviewer needs a live run against the Anthropic API before I would trust its notes.
- The sanity checks are declarative but the check kinds are a fixed set in code (`required`, `compare`, `date_order`, `formula_match`, `in_config`, `wording_block_exists`). A genuinely new kind of check needs a new kind handler. Adding a jurisdiction, a stage, a language or a new check that reuses an existing kind needs no code.
