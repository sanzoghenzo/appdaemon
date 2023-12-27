import pytest

from appdaemon.__main__ import ADMain


def test_main_no_cli_args():
    main = ADMain()
    with pytest.raises(SystemExit):
        main.main([])
