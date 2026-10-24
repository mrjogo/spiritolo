"""The Spiritolo service.

One process serves everything: the public recipe API, the operator (``/ops``)
API, the built React app as static files, and the pipeline executor that runs
queued jobs in a background thread against the same SQLite file. See
``spiritolo.main.create_app``.
"""
