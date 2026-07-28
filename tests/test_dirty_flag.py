from concurrent.futures import ThreadPoolExecutor

from codebase_indexer.dirty_flag import DirtyFlag


def test_dirty_flag_set_peek_and_clear():
    flag = DirtyFlag()

    assert flag.is_set() is False
    assert flag.check_and_clear() is False

    flag.set()

    assert flag.is_set() is True
    flag.set(False)
    assert flag.is_set() is False
    flag.set(True)
    assert flag.check_and_clear() is True
    assert flag.is_set() is False


def test_dirty_flag_remains_consistent_under_concurrent_access():
    flag = DirtyFlag()

    with ThreadPoolExecutor(max_workers=8) as executor:
        operations = [executor.submit(flag.set) for _ in range(20)]
        operations.extend(executor.submit(flag.is_set) for _ in range(20))
        for operation in operations:
            operation.result()

    assert flag.check_and_clear() is True
    assert flag.check_and_clear() is False
