"""Print a bcrypt hash for a password, e.g. for [auth.admin] password_hash in secrets.toml.

Run with: python scripts/hash_password.py
The password is read with getpass (not echoed) and never written anywhere.
"""

from getpass import getpass
import sys

import bcrypt


def main():
    password = getpass("Password: ")
    if getpass("Confirm password: ") != password:
        sys.exit("Passwords don't match.")
    if len(password) < 10:
        sys.exit("Use at least 10 characters.")
    print(bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode())


if __name__ == "__main__":
    main()
