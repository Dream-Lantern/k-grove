import unittest

from translation_contracts import demo, fingerprint, submit_revision, term_metrics


class TranslationTests(unittest.TestCase):
    def test_two_chapters_one_bounded_repair(self):
        result=demo()
        self.assertEqual(result['before']['hit_rate'],1)
        self.assertEqual(result['before']['strict_rate'],.5)
        self.assertEqual(result['before']['mixed_rate'],.5)
        self.assertEqual(result['after']['strict_rate'],1)
        self.assertEqual(result['file_index']['ch1']['version'],1)
        self.assertEqual(result['file_index']['ch2']['version'],2)
        self.assertEqual(result['semantic_quality'],'NOT_EVALUATED')

    def test_same_chapter_hit_is_not_strict(self):
        metrics=term_metrics({'chapter':'词元和标记'})
        self.assertEqual(metrics['hit_rate'],1)
        self.assertEqual(metrics['strict_rate'],0)
        self.assertEqual(metrics['mixed_rate'],1)

    def test_cross_chapter_drift_and_zero_coverage(self):
        metrics=term_metrics({'ch1':'词元','ch2':'标记'})
        self.assertEqual(metrics['hit_rate'],.5)
        self.assertEqual(metrics['mixed_rate'],0)
        missing=term_metrics({'ch1':'没有跟踪概念'})
        self.assertEqual(missing['coverage'],0)
        self.assertIsNone(missing['strict_rate'])
        self.assertIsNone(missing['hit_rate'])
        self.assertIsNone(term_metrics({})['coverage'])

    def test_teaching_code_exclusion(self):
        metrics=term_metrics({'ch1':'词元\n```text\n标记\n```\n`标记`'})
        self.assertEqual(metrics['strict_rate'],1)

    def test_version_and_budget_stop_overwrite(self):
        index={'ch2':{'text':'词元','version':2,'sha256':fingerprint('词元')}}
        with self.assertRaisesRegex(ValueError,'stale'):
            submit_revision(index,'ch2',fingerprint('旧文本'),'新文本',1)
        with self.assertRaisesRegex(ValueError,'budget'):
            submit_revision(index,'ch2',index['ch2']['sha256'],'新文本',0)
        self.assertEqual(index['ch2']['version'],2)


if __name__ == '__main__': unittest.main()
