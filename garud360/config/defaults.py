# garud360/config/defaults.py
"""Product-level constants and the FIRST-RUN default login.

Edit this file to change the factory credentials.

IMPORTANT: these credentials are only used to create the very first admin account
when the user database is empty. Once the app has run once, change passwords from
the in-app *Users* page. To restore the factory admin later, run:

    python -m garud360 --reset-admin
"""

# ---- First-run login (universal default) ---------------------------------------
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "Garud@360"

# True  -> the default admin must choose a new password at the first sign-in.
# False -> the default password keeps working until someone changes it.
FORCE_PASSWORD_CHANGE_ON_FIRST_LOGIN = True

# ---- Password / login policy ---------------------------------------------------
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72          # bcrypt hard limit
LOGIN_MAX_ATTEMPTS = 5           # failures before a temporary lockout
LOGIN_LOCKOUT_SECONDS = 30

# ---- Capacity limits -----------------------------------------------------------
MAX_SPACES = 50
MAX_CAMERAS_PER_SPACE = 10

# ---- Roles ---------------------------------------------------------------------
ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"
ROLES = (ROLE_ADMIN, ROLE_OPERATOR)
