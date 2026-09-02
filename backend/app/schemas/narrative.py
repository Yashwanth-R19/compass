from pydantic import BaseModel

# The four reasons "available: false" can mean (session 12, Part E) --
# distinct states a UI can word differently: "no_keys"/"pool_exhausted" are
# both "try again later, this is a supply problem, not yours", "rejected"
# means a generation happened and failed the output validator, and
# "disabled" covers everything else that isn't one of the three LLM-pool
# states -- today, only "the underlying computed data for this surface/
# subject isn't ready or doesn't exist yet" (an invalid subject, or a stage
# that hasn't reached a terminal status). Never a 500 for any of these --
# see app/api/narrative.py's module docstring.
NarrativeUnavailableReason = str


class NarrativeResponse(BaseModel):
    available: bool
    content: str | None = None
    provider: str | None = None
    model: str | None = None
    generated_at: str | None = None
    reason: str | None = None
