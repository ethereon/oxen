#!/usr/bin/env python3

from oxen import Session, Process, Watch, auto_rsync


def run():
    session = Session(name='Sample')

    session += Process(
        'python',
        '-c',
        'import time; [print(i) or time.sleep(0.5) for i in range(10)]',
        name='Counter'
    )

    session += Watch(
        path='/tmp/oxen-test/dest',
        handler=Process('echo', 'Modification detected.'),
        name='Watch Echo'
    )

    session += auto_rsync(
        source='/tmp/oxen-test/source',
        dest='/tmp/oxen-test/dest',
        name='Auto Sync'
    )

    session.run()


def prepare_test_data():
    import os
    os.makedirs('/tmp/oxen-test/source', exist_ok=True)
    os.makedirs('/tmp/oxen-test/dest', exist_ok=True)
    with open('/tmp/oxen-test/source/test-file', 'w') as outfile:
        outfile.write('Testing')


prepare_test_data()
run()
