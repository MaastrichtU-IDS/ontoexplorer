"""The worker must not log full httpx request URLs (federation apikey_param keys ride in them)."""
import logging

from ontoexplorer.modules.jobs import tasks


def test_suppress_http_client_logs_sets_warning():
    names = ("httpx", "httpcore")
    prior = {n: logging.getLogger(n).level for n in names}
    root_prior = logging.getLogger().level
    try:
        for n in names:
            logging.getLogger(n).setLevel(logging.INFO)
        tasks._suppress_http_client_logs()
        for n in names:
            assert logging.getLogger(n).level == logging.WARNING
        assert logging.getLogger().level == root_prior
    finally:
        for n in names:
            logging.getLogger(n).setLevel(prior[n])


def test_handler_is_connected_to_worker_process_init():
    from celery.signals import worker_process_init

    # Receivers are held as weakrefs to the (module-level) handler function.
    assert tasks._suppress_http_client_logs in [r() for _, r in worker_process_init.receivers]
