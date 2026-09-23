"""Turn the Offerings tab into requests, each scoped to the day it is for.

Each offered clinic instance becomes a CLINIC request tagged IMPORT_TAG, so the Puppet
Master can see, edit or delete it before solving. The request names the clinic and when,
and nothing else: `REQUEST activities.clinics.archery_1_2 DURING blocks.clinic_2`. Who may
run it is already written down, as the skill each of its positions needs, so a request that
said `ANY 1 staff.all` as well would be saying it twice. The clinic runs fully staffed or
not at all, because filling one position of an instance fills them all
(`solver.structural`), which is what lets the request stop at naming it.

Loading a date imports its clinics on the way in when none carry IMPORT_TAG for it yet.
Load offerings imports them again, first removing every imported request for that date, so
the day's requests mirror its Offerings tab.
"""

from dataclasses import replace
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
        during = f"ALL_OF {{{blocks}}}" if len(offering.blocks) > 1 else blocks
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


def merge(existing: list[Request], generated: list[Request], target: date) -> list[Request]:
    """Existing requests minus the date's old generated ones, plus the new generated ones."""
    kept = [r for r in existing if not is_generated(r, target)]
    return kept + list(generated)


def is_generated(request: Request, target: date) -> bool:
    """Whether a request was generated from the Offerings tab for this date."""
    prefix = f"offering:{target.isoformat()}:"
    return request.id.startswith(prefix) and IMPORT_TAG in request.tags


def has_offerings_loaded(requests: tuple[Request, ...], target: date) -> bool:
    """Whether any request imported from the Offerings tab exists for the date."""
    return any(is_generated(r, target) for r in requests)


def import_if_missing(dataset: Dataset, book) -> tuple[Dataset, int]:
    """The dataset with its date's clinics imported and saved, if none were yet.

    Returns it and how many were imported. A day that already has some keeps them as they
    are, edits and deletions included: only Load offerings imports a day's clinics again.
    A day whose Offerings tab is still empty imports nothing, so the next load tries again.
    """
    if has_offerings_loaded(dataset.requests, dataset.target):
        return dataset, 0
    imported = generated_requests(dataset)
    if not imported:
        return dataset, 0
    book.put(imported)
    return replace(dataset, requests=dataset.requests + tuple(imported)), len(imported)
