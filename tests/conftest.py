import pytest

from preheat.fixture import day


@pytest.fixture(params=["current", "insulated"])
def nominal(request):
    return request.param, day("nominal", request.param)
