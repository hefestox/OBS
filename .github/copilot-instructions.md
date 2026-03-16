# GitHub Copilot Instructions for IMAC API

This is a Django REST Framework project for environmental licensing ("licenciamento ambiental"). Follow these guidelines to ensure code consistency and stability.

## 🏗 Project Architecture

- **Root Configuration**: Located in `settup/` (not `imac/settup`).
- **Apps Directory**: All domain logic resides in `imac/<app_name>/`.
- **API Structure**: Do not put views in `views.py`. Use `imac/<app>/api/views/` and `imac/<app>/api/serializers/`.
- **Database**: PostgreSQL with PostGIS (`django.contrib.gis`).
- **Async**: Uses Django Channels and Daphne.

## 🛡 Critical Patterns & Conventions

### 1. Audit Logging (Mandatory)
**Every** concrete model must be decorated with `django-pgtrigger` to log updates and deletions.
- Import `pgtrigger` and `REGISTER_SCRIPT_CHOICES`.
- Apply the `@pgtrigger.register` decorator with `log_update_<model>` and `log_delete_<model>`.

**Example:**
```python
import pgtrigger
from django.db import models
from imac.logs.models import REGISTER_SCRIPT_CHOICES

@pgtrigger.register(
    pgtrigger.Trigger(
        name='log_update_mymodel',
        when=pgtrigger.Before,
        operation=pgtrigger.Update,
        func=REGISTER_SCRIPT_CHOICES['update']
    ),
    pgtrigger.Trigger(
        name='log_delete_mymodel',
        when=pgtrigger.Before,
        operation=pgtrigger.Delete,
        func=REGISTER_SCRIPT_CHOICES['delete']
    )
)
class MyModel(models.Model):
    # ... fields ...
```

### 2. Model Fields
- Use `django_extensions.db.models.CreationDateTimeField` and `ModificationDateTimeField` for tracking timestamps.
- Include a `last_user_register` field (CharField) to track the user who made the last change.

### 3. API Views
- Use Class-Based Views (CBVs) from DRF.
- Place view logic in `imac/<app>/api/views/<resource>.py`.
- Place serializers in `imac/<app>/api/serializers/<resource>.py`.

## 🛠 Development Workflow

### Test-Driven Development (TDD)
- Start every feature or regression fix by writing failing unit/integration tests that encode the required behavior.
- Keep the red → green → refactor loop tight; do not write production code without a covering test.
- Expand the pytest/DRF test suites instead of relying on manual verification. Every bug fix must ship with a regression test.
- CI must exit cleanly (`pytest`, `python manage.py test`, linters) before code review.

### Database Migrations
Because of `pgtrigger`, migrations are critical.
- Always run `python manage.py makemigrations` after modifying models.
- Triggers are installed via migrations.

### Running the Project
- **Server**: `python manage.py runserver 0.0.0.0:8000`
- **Tests**: `python manage.py test`
- **Docker**: Services defined in `docker-compose.yml` (`django-rest-api`, `postgres`).

## 📦 Key Dependencies
- `django-pgtrigger`: Audit logging.
- `django-rest-framework-gis`: GeoJSON support.
- `pyreportjasper`: JasperReports generation (templates in `core/*.jrxml`).
- `drf-spectacular`: API Schema/Documentation.
