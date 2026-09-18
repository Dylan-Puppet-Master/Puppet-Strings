"""Turn the Offerings tab into requests on the Requests sheet.

Each offered clinic instance becomes a CLINIC request tagged GENERATED_TAG and filed in the
clinic group, so the Puppet Master can see, edit or delete it before solving. One person is
asked for; the rest of the positions fill because a clinic runs fully staffed or not at
all. Loading again first removes every generated request for that date, so the Requests
sheet mirrors the Offerings tab.
"""

from datetime import date

from puppet_strings.model import CLINIC_GROUP, Dataset, Priority, Request

GENERATED_TAG = "generated"


def generated_requests(dataset: Dataset) -> list[Request]:
    """One CLINIC request per offering, for the dataset's target date."""
    target = dataset.target.isoformat()
    requests = []
    for offering in dataset.offerings:
        blocks = " + ".join(f"block.{b}" for b in offering.blocks)
        during = f"ALL_OF {{{blocks}}}" if len(offering.blocks) > 1 else blocks
        name = dataset.activities[offering.activity].name
        skedge = (
            f"REQUEST ANY_1_OF staff.all DO activity.{offering.activity} "
            f"DURING {during} ON {target}"
        )
        requests.append(
            Request(
                id=f"offering:{target}:{offering.activity}:{offering.blocks[0]}",
                description=f"{name} in {', '.join(offering.blocks)}",
                skedge=skedge,
                priority=Priority.CLINIC,
                tags=(GENERATED_TAG,),
                groups=(CLINIC_GROUP,),
                created=dataset.target,
            )
        )
    return requests


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
