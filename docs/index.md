# Puppet Strings

Puppet Strings builds the daily staff schedule for Camp Augusta. The Puppet Master keeps camp data in Google Sheets, writes scheduling rules as **requests** in a small declarative language called **Skedge**, and presses Solve. The solver assigns staff to the clinics on the Offerings sheet, fits in breaks, counselor hours, and other tasks specifided by the Puppet Master. It then can publish two printable views back to Google Sheets.

![The request manager](img/app.png)

## The Daily Loop

1. Fill in tomorrow's **Offerings** tab to define the clinics that will run.
2. Open the request manager (`puppet-strings app`), which imports the day's clinics from its Offerings tab, then add or adjust requests acccording to the shared camp schedule request doc or personl requests from staff members. This is also where I would request that staff members be trained on clinics.
3. Press **Solve**. Read the staff view, the clinic view and the report of anything that could not be satisfied.
4. Press **Publish**. The schedule lands in that day's own formatted spreadsheet.

If the day is already published and someone turns up ill or short of sleep, see
[Same-day changes](same-day.md).

## Development Thought Process
I (Dylan) designed Puppet Strings and Skedge based on my opinion that the hard part of designing scheduling software is not solving a constraint problem so much as expressing a constraint problem. Solvers such as Google's open source OR-Tools have essentially solved the problem of efficient constraint optimization, though the code written within these frameworks is often verbose and unintuitive. OR-Tools is designed to be capable of expressing optimization problems across a wide range of fields with a high level of control. I deemed the gap between natural language requests and their corresponding OR-Tools representations too wide to be workable.

I therefore wanted a custom declarative language that was expressive enough to convey complex scheduling constraints while still being human readable. This is what Skedge aims to be. Skedge is a high level representation of schedule constraints that compiles to OR-Tools code. Very little is hard-coded into the Puppet Strings solver, with almost all of the constraints coming from editable Skedge code. In this way, Puppet Strings is NOT an out-of-the-box solution for scheduling at Camp Augusta. Instead, it is a general computer-assisted scheduling framework that Puppet Masters can program within. 

## AI Usage Disclosure
As interesting as implementing a new declarative programming language sounds, it is unfrotunatlely not within the scope of the Puppet Master role to spend considerable amounts of time learning to do this. I provided Claude Code with a detailed, high level specification for Skedge and the Puppet Strings software, then guided the LLM to produce software to my liking. The vast majority of this documentation is written and kept up to date by Claude, and more-or-less every line of code was written with Claude Code.

## Where Things Live

| Thing | Where |
|---|---|
| Clinics, positions, RAL minimums | Clinic_Data spreadsheet |
| Who is checked off on what | Skills spreadsheet |
| Staff categories | A `Staff Categories` spreadsheet in each span's folder |
| Tomorrow's clinics | The Offerings tab of that day's spreadsheet |
| The grid a new day starts from | Offerings tab of Clinic_Schedule |
| Blocks, calendar, mappings, adjustments | The config spreadsheet |
| Requests | A file on the Puppet Master's computer, handed over with [Export and Import](sheets.md#requests-on-this-computer) |
| Published schedules | One spreadsheet per day, in the [schedules tree](sheets.md#the-schedules-tree) |
| The code | This repository, one Python package |

Start with [Install and set up](install.md).
