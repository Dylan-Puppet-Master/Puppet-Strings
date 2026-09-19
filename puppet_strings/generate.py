"""Turn the Offerings tab into requests on the Requests sheet.

Each offered clinic instance becomes a CLINIC request tagged GENERATED_TAG, so the Puppet
Master can see, edit or delete it before solving. The request asks for every position by
name: one `REQUEST … AS_ROLE` line per position on Clinic_Data, facilitators first and
then any lifeguards. The lines of one request stand or fall together, so a clinic still
runs fully staffed or not at all, and now the request says so out loud instead of leaving
it to the skill matching to work out. Loading again first removes every generated request
for that date, so the Requests sheet mirrors the Offerings tab.
"""

from datetime import date

from puppet_strings.model import Activity, Dataset, Priority, Request

GENERATED_TAG = "generated"


def generated_requests(dataset: Dataset) -> list[Request]:
    """One CLINIC request per offering, for the dataset's target date."""
    target = dataset.target.isoformat()
    requests = []
    for offering in dataset.offerings:
        blocks = " + ".join(f"block.{b}" for b in offering.blocks)
        during = f"ALL_OF {{{blocks}}}" if len(offering.blocks) > 1 else blocks
        activity = dataset.activities[offering.activity]
        name = activity.name
        skedge = _skedge(activity, during, target)
        requests.append(
            Request(
                id=f"offering:{target}:{offering.activity}:{offering.blocks[0]}",
                description=f"{name} in {', '.join(offering.blocks)}",
                skedge=skedge,
                priority=Priority.CLINIC,
                tags=(GENERATED_TAG,),
                created=dataset.target,
            )
        )
    return requests


def _skedge(activity: Activity, during: str, target: str) -> str:
    """One REQUEST line per position of the clinic, each naming the role it asks for.

    A clinic with no positions on Clinic_Data gets the one roleless line it always got;
    asking for no role at all is still a request that the clinic runs.
    """
    head = f"REQUEST ANY_1_OF staff.all DO activity.{activity.id}"
    tail = f"DURING {during} ON {target}"
    if not activity.positions:
        return f"{head} {tail}"
    return "\n".join(f"{head} AS_ROLE role.{p.role} {tail}" for p in activity.positions)


def merge(existing: list[Request], generated: list[Request], target: date) -> list[Request]:
    """Existing requests minus the date's old generated ones, plus the new generated ones."""
    kept = [r for r in existing if not is_generated(r, target)]
    return kept + list(generated)


def is_generated(request: Request, target: date) -> bool:
    """Whether a request was generated from the Offerings tab for this date."""
    prefix = f"offering:{target.isoformat()}:"
    return request.id.startswith(prefix) and GENERATED_TAG in request.tags


def has_offerings_loaded(requests: tuple[Request, ...], target: date) -> bool:
    """Whether any generated request exists for the date."""
    return any(is_generated(r, target) for r in requests)
