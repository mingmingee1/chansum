"""Explicit fixture server for browser tests; never import from run.py."""
import os
from pathlib import Path

import uvicorn

from chansum.app import create_app
from tests.fixture_engine import FixtureEngine

if __name__=='__main__':
    fixture=FixtureEngine()
    fixture.delay=float(os.environ.get('CHANSUM_TEST_DELAY','0'))
    fixture.edit_delay=float(os.environ.get('CHANSUM_TEST_EDIT_DELAY','0'))
    uvicorn.run(create_app(data_dir=Path(os.environ['CHANSUM_TEST_DATA']),private_dir=Path(os.environ['CHANSUM_TEST_PRIVATE']),engine=fixture),host='127.0.0.1',port=int(os.environ.get('CHANSUM_TEST_PORT','9420')),access_log=False)
