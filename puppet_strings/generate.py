"""Turn the Offerings tab into requests, each scoped to the day it is for.

Each offered clinic instance becomes a CLINIC request tagged IMPORT_TAG. The request names
the clinic and when, and nothing else: `REQUEST activities.clinics.archery_1_2 DURING
blocks.clinic_2`. Who may run it is already written down, as the skill each of its
positions needs, so a request that said `ANY 1 staff` as well would be saying it twice.
The clinic runs fully staffed or not at all, because filling one position of an instance
fills them all (`solver.structural`), which is what lets the request stop at naming it.

They are made afresh on every load and never saved as they are: the Offerings tab is where
they live, and a season of them is most of the requests there would be. One that is edited
is saved like any other request, under its own id, and from then on the saved one is read
in place of the one made. One cannot be deleted, since the next load would make it again:
it is taken off the Offerings tab instead. Load offerings throws the saved ones away, so
the day's clinics are the Offerings tab's again.
"""

from datetime import date

from puppet_strings.model import DAY, Dataset, Priority, Request

IMPORT_TAG = "clinic_import"


def generated_requests(dataset: Dataset) -> list[Request]:
    """One CLINIC request per offering, for the dataset's target date, scoped to that day.

    A day's offerings are the day's alone, so no other day reads them.
    """
    target = dataset.target.isoformat()
    requests = []
    for offering in dataset.offerings:
        blocks = " + ".join(f"blocks.{b}" for b in offering.blocks)
        during = f"ALL {{{blocks}}}" if len(offering.blocks) > 1 else blocks
        name = dataset.activities[offering.activity].name
        skedge = f"REQUEST activities.clinics.{offering.activity} DURING {during} ON {target}"
        requests.append(
            Request(
                id=f"offering:{target}:{offering.activity}:{offering.blocks[0]}",
                description=f"{name} in {', '.join(offering.blocks)}",
                skedge=skedge,
                priority=Priority.CLINIC,
                tags=(IMPORT_TAG,),
                created=dataset.target,
                scope=dataset.scope(DAY),
            )
        )
    return requests


def with_offerings(dataset: Dataset) -> tuple[Request, ...]:
    """The dataset's requests, and a clinic request for each offering none of them replaces."""
    saved = {r.id for r in dataset.requests}
    made = (r for r in generated_requests(dataset) if r.id not in saved)
    return dataset.requests + tuple(made)


def is_imported(request: Request) -> bool:
    """Whether a request is a clinic made from an Offerings tab, whichever day's."""
    return request.id.startswith("offering:") and IMPORT_TAG in request.tags


def is_generated(request: Request, target: date) -> bool:
    """Whether a request is a clinic made from the Offerings tab for this date."""
    return is_imported(request) and request.id.startswith(f"offering:{target.isoformat()}:")
