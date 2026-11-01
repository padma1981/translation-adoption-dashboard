# Translation Tool Adoption Dashboard (demo)

A Streamlit dashboard measuring how contact center agents adopt a live translation
tool for Spanish, Portuguese, Mandarin and Vietnamese callers. **All data is
synthetic**; there is no real customer or employee data in this repo.

Pages: Overview (adoption donut, agents repeatedly not using the tool), Agents &
Teams, Languages, Operational Impact, Cost, Data Quality and (admins only) User
management. Sign-in is required; what you see depends on your role.

| Role | Sees |
|---|---|
| admin | Every page, all teams, all CSV exports, User management |
| supervisor | Every page except Data Quality and User management, limited to their own team (Team and Supervisor filters are locked) |
| viewer | Overview adoption donut and its summary CSV only |

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Create the break-glass admin (see below), then:

```bash
streamlit run app/streamlit_app.py
```

Without a `[connections.gsheets]` block in your secrets, users are stored in a
local SQLite file at `data/users/users.db` (git-ignored). Without an `[auth]`
block the app shows a setup message instead of opening.

Tests and data checks:

```bash
pytest
```

To regenerate the synthetic data (writes `data/raw/*.parquet`, then runs the checks):

```bash
python data_gen/generate.py
```

## Secrets

Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` (git-ignored)
and fill it in. Never commit real secrets.

### Break-glass admin

One admin lives in secrets rather than the user store, so it always works, even
when the Google Sheet is unavailable.

1. Run `python scripts/hash_password.py`, type a password (at least 10
   characters; it is not shown) and copy the printed `$2b$12$...` hash.
2. In `secrets.toml`:

   ```toml
   [auth]
   session_timeout_minutes = 480

   [auth.admin]
   username = "admin"
   name = "Dashboard Admin"
   password_hash = "$2b$12$...paste the hash..."
   ```

To change this admin's password, generate a new hash and replace `password_hash`.

### Google Sheets user store

1. In the [Google Cloud console](https://console.cloud.google.com/), create (or pick)
   a project and enable the **Google Sheets API** and **Google Drive API**.
2. Create a **service account** (IAM & Admin → Service accounts), open it, and
   under **Keys** add a JSON key. Download it; this file is a secret.
3. Create a Google Sheet and add a worksheet named **`users`** whose first row
   holds these headers:

   ```
   username, name, email, role, team, password_hash, status, must_change_password, requested_role, requested_team, reason, created_at, approved_by, approved_at, updated_at
   ```

   (Phase 4 will add a `feedback` worksheet to the same sheet.)
4. **Share** the sheet with the service account's `client_email` as an **Editor**.
5. Add a `[connections.gsheets]` block to your secrets: `spreadsheet` is the
   sheet's URL, and the other keys are copied from the JSON key file (see
   `.streamlit/secrets.toml.example`; keep the `\n` line breaks in `private_key`).

The app reads and writes users only through `src/users.py`. Passwords are
stored only as bcrypt hashes and are never shown or logged.

## How sign-up and approval work

1. A new user clicks **Request access** on the sign-in page and enters name,
   email, username, password, the role they want (supervisor or viewer; admin
   can't be requested), their team (required for supervisors) and a reason.
   The request is saved with status `pending`.
2. Until approved they see "Your account is not active yet" when signing in.
3. An admin opens **User management** (the menu shows the number of pending
   requests), picks the final role and team, and approves or rejects.
4. Admins can later change a user's role or team, deactivate or reactivate
   them, or reset their password. A reset shows a temporary password once; the
   user must change it right after signing in. Admins can't deactivate or
   demote themselves.

Other rules: 5 wrong passwords in a session block sign-in for 5 minutes;
sessions end after `session_timeout_minutes`; passwords need at least 10
characters with letters and numbers.

## Deploy to Streamlit Community Cloud

1. Push this repo to GitHub (it holds no real data and can be public).
2. At [share.streamlit.io](https://share.streamlit.io/) choose **Create app**,
   pick the repo and branch `main`, and set the main file path to
   `app/streamlit_app.py`.
3. Paste the contents of your `secrets.toml` (`[auth]`, `[auth.admin]` and
   `[connections.gsheets]`) into **Manage app → Settings → Secrets** and save.
   The app restarts with them.
4. Sign in as the break-glass admin and approve the first requests.

The committed Parquet files in `data/raw/` keep the demo data identical on every start.
