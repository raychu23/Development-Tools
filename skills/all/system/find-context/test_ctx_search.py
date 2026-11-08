import os
import tempfile
import unittest

import ctx_search as cs


class TestCtxSearch(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, 'Context', 'proj', 'T1-x'))
        os.makedirs(os.path.join(self.root, 'Deleted', 'T9'))
        os.makedirs(os.path.join(self.root, 'a', 'b', 'c', 'd', 'e', 'f', 'g'))
        self.w('rules.md', '```notes\n0 version control\n    deleting                commit first, then git rm      never plain rm\n```\n')
        self.w('Context/proj/T1-x/0 start.md', 'status    blocked by a duplicate claim\nnext    unblock\n')
        self.w('Context/proj/T1-x/notes.md', 'deleting is not here')
        self.w('Deleted/T9/0 start.md', 'deleting old')
        self.w('a/b/c/d/e/f/g/0 start.md', 'too deep deleting')
        self.w('AGENTS.md', '- ' + 'x ' * 150 + 'filler. For a correction, record old -> new -> scope. ' + 'y ' * 100)

    def w(self, rel, text):
        with open(os.path.join(self.root, rel), 'w', encoding='utf-8') as f:
            f.write(text)

    def test_corpus_is_curated_files_only(self):
        files = sorted(cs.corpus(self.root))
        self.assertEqual(files, ['AGENTS.md', 'Context/proj/T1-x/0 start.md', 'rules.md'])

    def test_rules_folder_is_in_corpus(self):
        os.makedirs(os.path.join(self.root, 'rules'))
        self.w('rules/bots.md', 'rotate after ~30 turns')
        self.assertIn('rules/bots.md', cs.corpus(self.root))

    def test_finds_rule_with_stemmed_words(self):
        hits = cs.search('how do I delete a file?', 3, root=self.root)
        self.assertEqual(hits[0]['path'], 'rules.md')
        self.assertIn('git rm', hits[0]['text'])
        self.assertEqual(hits[0]['heading'], '0 version control')

    def test_long_prose_line_is_split_and_keeps_line_number(self):
        hits = cs.search('what format does a correction record use', 3, root=self.root)
        top = [h for h in hits if h['path'] == 'AGENTS.md'][0]
        self.assertIn('record old -> new -> scope', top['text'])
        self.assertTrue(top['lines'].startswith('1-'))
        self.assertLess(len(top['text']), 600)

    def test_overlapping_sections_are_merged(self):
        hits = cs.search('blocked duplicate claim unblock', 5, root=self.root)
        starts = [h['lines'] for h in hits if h['path'] == 'Context/proj/T1-x/0 start.md']
        self.assertEqual(len(starts), 1)

    def test_short_ids_are_kept(self):
        self.assertEqual(cs.terms('why is T3 blocked in q4?'), ['t3', 'blocked', 'q4'])

    def test_line_numbers_on_a_multi_line_file(self):
        self.w('Context/proj/T1-x/1 takeaways.md', '\n'.join(f'line {n}' for n in range(1, 30)) + '\nmarker zebra here\n')
        hit = [h for h in cs.search('zebra marker', 5, root=self.root) if h['path'].endswith('1 takeaways.md')][0]
        a, b = map(int, hit['lines'].split('-'))
        self.assertTrue(a <= 30 <= b, hit['lines'])

    def test_depth_six_is_included(self):
        os.makedirs(os.path.join(self.root, 'a', 'b', 'c', 'd', 'e', 'f'), exist_ok=True)
        self.w('a/b/c/d/e/f/0 start.md', 'six deep')
        self.assertIn('a/b/c/d/e/f/0 start.md', cs.corpus(self.root))

    def test_front_matter_is_not_a_heading(self):
        self.w('Context/proj/T1-x/2 insights.md', '---\nstate: blocked\n---\nquokka finding\n')
        hit = [h for h in cs.search('quokka', 5, root=self.root)][0]
        self.assertNotEqual(hit['heading'], '---')

    def test_fts_syntax_in_question_is_harmless(self):
        cs.search('NEAR(a b) "x" * col:y ^AND', 5, root=self.root)

    def test_no_terms_no_hits(self):
        self.assertEqual(cs.search('what is the', 5, root=self.root), [])


if __name__ == '__main__':
    unittest.main()
