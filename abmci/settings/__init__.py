import os

# Par défaut : prod (DEBUG=False). Le mode dev doit être demandé explicitement (DJANGO_ENV=dev).
env = os.environ.get('DJANGO_ENV', 'prod')

if env == 'dev':
    from .dev import *
else:
    from .prod import *
