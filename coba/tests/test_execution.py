
import unittest
import traceback

from pathlib import Path

from coba.execution import DiskCache, UniversalLogger

class UniversalLogger_Tests(unittest.TestCase):

    def test_log(self):

        actual_prints = []

        logger = UniversalLogger(print_function = lambda m,e: actual_prints.append((m,e)) )

        logger.log('a', end='b')
        logger.log('c')
        logger.log('d')

        self.assertEqual(actual_prints[0][0][20:], 'a' )
        self.assertEqual(actual_prints[0][1]     , 'b' )
        self.assertEqual(actual_prints[1][0]     , 'c' )
        self.assertEqual(actual_prints[1][1]     , None)
        self.assertEqual(actual_prints[2][0][20:], 'd' )
        self.assertEqual(actual_prints[2][1]     , None)

    def test_log_with_1(self):

        actual_prints = []

        logger = UniversalLogger(print_function = lambda m,e: actual_prints.append((m,e)) )

        with logger.log('a', end='b'):
            logger.log('c')
            logger.log('d')
        logger.log('e')

        self.assertEqual(actual_prints[0][0][20:], 'a' )
        self.assertEqual(actual_prints[0][1]     , 'b' )
        self.assertEqual(actual_prints[1][0]     , 'c' )
        self.assertEqual(actual_prints[1][1]     , None)
        self.assertEqual(actual_prints[2][0][20:], '  * d')
        self.assertEqual(actual_prints[2][1]     , None)
        self.assertEqual(actual_prints[4][0][20:], 'e')
        self.assertEqual(actual_prints[4][1]     , None)

    def test_log_with_2(self):

        actual_prints = []

        logger = UniversalLogger(print_function = lambda m,e: actual_prints.append((m,e)) )

        with logger.log('a', end='b'):
            logger.log('c')
            with logger.log('d'):
                logger.log('e')
            logger.log('f')
        logger.log('g')

        self.assertEqual(actual_prints[0][0][20:], 'a' )
        self.assertEqual(actual_prints[0][1]     , 'b' )
        self.assertEqual(actual_prints[1][0]     , 'c' )
        self.assertEqual(actual_prints[1][1]     , None)
        self.assertEqual(actual_prints[2][0][20:], '  * d')
        self.assertEqual(actual_prints[2][1]     , None)
        self.assertEqual(actual_prints[3][0][20:], '    > e')
        self.assertEqual(actual_prints[3][1]     , None)
        self.assertEqual(actual_prints[5][0][20:], '  * f')
        self.assertEqual(actual_prints[5][1]     , None)
        self.assertEqual(actual_prints[7][0][20:], 'g')
        self.assertEqual(actual_prints[7][1]     , None)

    def test_log_exception_1(self):
        actual_prints = []

        logger = UniversalLogger(print_function = lambda m,e: actual_prints.append((m,e)))

        try:
            raise Exception("Test Exception")
        except Exception as ex:
            logger.log_exception(ex)

            tb = ''.join(traceback.format_tb(ex.__traceback__))
            msg = ''.join(traceback.TracebackException.from_exception(ex).format_exception_only())

            expected_msg = f"\n\n{tb}\n  {msg}"

            self.assertTrue(hasattr(ex, '__logged__'))
            self.assertEqual(actual_prints[0][0][20:], expected_msg)
            self.assertEqual(actual_prints[0][1], None)
            self.assertEqual(len(actual_prints), 1)

    def test_log_exception_2(self):
        actual_prints = []
        exception = Exception("Test Exception")

        logger = UniversalLogger(print_function = lambda m,e: actual_prints.append((m,e)))

        logger.log('a', end='b')
        logger.log_exception(exception)

        tb = ''.join(traceback.format_tb(exception.__traceback__))
        msg = ''.join(traceback.TracebackException.from_exception(exception).format_exception_only())

        expected_msg = f"\n\n{tb}\n  {msg}"

        self.assertTrue(hasattr(exception, '__logged__'))
        self.assertEqual(actual_prints[0][0][20:], "a")
        self.assertEqual(actual_prints[0][1]     , "b")
        self.assertEqual(actual_prints[1][0][20:], '')
        self.assertEqual(actual_prints[1][1]     , None)
        self.assertEqual(actual_prints[2][0][20:], expected_msg)
        self.assertEqual(actual_prints[2][1], None)

        logger.log_exception(exception)

class DiskCache_Tests(unittest.TestCase):

    def setUp(self):
        if Path("coba/tests/.temp/test.csv.gz").exists():
            Path("coba/tests/.temp/test.csv.gz").unlink()

    def tearDown(self) -> None:
        if Path("coba/tests/.temp/test.csv.gz").exists():
            Path("coba/tests/.temp/test.csv.gz").unlink()

    def test_creates_directory(self):
        try:
            cache = DiskCache("coba/tests/.temp/folder1/folder2")
            
            cache.put("test.csv", b"test")
            self.assertTrue("test.csv"    in cache)

        finally:
            if Path("coba/tests/.temp/folder1/folder2/test.csv.gz").exists():
                Path("coba/tests/.temp/folder1/folder2/test.csv.gz").unlink()
            
            if Path("coba/tests/.temp/folder1/folder2/").exists():
                Path("coba/tests/.temp/folder1/folder2/").rmdir()
            
            if Path("coba/tests/.temp/folder1/").exists():
                Path("coba/tests/.temp/folder1/").rmdir()
            



    def test_write_csv_to_cache(self):

        cache = DiskCache("coba/tests/.temp")

        self.assertFalse("test.csv"    in cache)
        cache.put("test.csv", b"test")
        self.assertTrue("test.csv" in cache)

        self.assertEqual(cache.get("test.csv"), b"test")
    
    def test_rmv_csv_from_cache(self):

        cache = DiskCache("coba/tests/.temp/")

        self.assertFalse("test.csv"    in cache)
        
        cache.put("test.csv", b"test")
        
        self.assertTrue("test.csv"    in cache)

        cache.rmv("test.csv")

        self.assertFalse("test.csv"    in cache)

if __name__ == '__main__':
    unittest.main()