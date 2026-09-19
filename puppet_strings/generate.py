"""Turn the Offerings tab into requests on the Requests sheet.

Each offered clinic instance becomes a CLINIC request tagged GENERATED_TAG, so the Puppet
Master can see, edit or delete it before solving. The request names every position the
clinic wants rather than asking for one person and leaving the skill matching to work the
rest out: `AS_ROLE EACH_OF {role.first + role.second}`, facilitators first and then any
lifeguards. `EACH_OF` is what makes each position a separate choice of person; `ALL_OF`
would ask one person to hold them all. A clinic still runs fully staffed or not at all,
because filling one position of an instance fills them all (`solver.structural`).
Loading again first removes every generated request for that date, so the Requests sheet
mirrors the Offerings tab.
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
    """One request naming every position of the clinic.

    Two or more positions take `EACH_OF` over the set of roles, which is how Skedge says
    "each of these, chosen separately"; one position takes the role on its own, because a
    one-item set takes no quantifier. A clinic with no positions on Clinic_Data gets the
    roleless request it always got: asking for no role is still asking that it runs.
    """
    head = f"REQUEST ANY_1_OF staff.all DO activity.{activity.id}"
    tail = f"DURING {during} ON {target}"
    roles = [f"role.{p.role}" for p in activity.positions]
    if not roles:
        return f"{head} {tail}"
    if len(roles) == 1:
        return f"{head} AS_ROLE {roles[0]} {tail}"
    return f"{head} AS_ROLE EACH_OF {{{' + '.join(roles)}}} {tail}"


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
