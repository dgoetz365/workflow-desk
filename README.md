# Workflow Desk

Review equipment requests, reserve available stock, and record returns for a fictional community workshop.

**Python 3.12+ · SQLite · JavaScript · No runtime dependencies**

[Full guide](docs/guide.md) · [Portfolio](https://github.com/dgoetz365) · [MIT license](LICENSE)

## Quick start

```sh
git clone https://github.com/dgoetz365/workflow-desk.git
cd workflow-desk
python app.py seed
python app.py run
```

Open http://127.0.0.1:8765. The queue starts with fictional borrowers and equipment requests. Stop with Ctrl+C; saved work stays in `.local/workflow.sqlite3`. Seeding again preserves existing records.

On Windows, `py -3.12` can replace `python`. If you already cloned the repo, start with the Python commands from its root.

## Try it

Approve **Mira Chen** for two drills, then try approving **Theo Park** for two more. The app rejects the second request because only one drill is free. Record Mira’s return and approve Theo again.

## Engineering highlights

- **Inventory integrity:** approvals and returns update allocations and history in one transaction.
- **Safe review:** version checks prevent a decision made from an old workspace from overwriting newer work.
- **Retry handling:** an exact repeated command returns its saved receipt without reserving equipment twice.

[Application and storage](app.py) · [Tests](tests/) · [Engineering decisions](docs/decisions.md)

## Tests and scope

```sh
python -m unittest discover -s tests -v
```

A local, single-user demonstration with synthetic data and no authentication. It supports complete returns, not partial returns or date-based bookings. Browser rendering has not been verified.

Built by [Daniel Goetz](https://github.com/dgoetz365) as an independent portfolio example. Employer code and data are not included.
