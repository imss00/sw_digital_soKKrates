"""저널 기사소개(article_intros)에 LLM이 입력 라벨("기사 제목:", "기사 요약:")을
그대로 흘려 넣은 경우를 방어적으로 제거하는 로직 테스트.

배경: journal_composer의 기사소개 프롬프트가 참고 데이터를 "기사 제목: {title}\n
기사 요약: {summary}" 형식으로 넘기는데, 구버전 프롬프트로 생성된 일부 저널은 모델이
그 라벨을 그대로 응답 맨 앞에 복사해 버렸다(줄바꿈 없이 본문에 바로 이어붙은 경우도 있음).
프롬프트는 이후 생성분에 대해 고쳤지만, 이미 DB에 저장된 과거 데이터는 소급 반영되지
않으므로 Journal.to_dict()가 조회 시점에 한 번 더 걸러낸다.
"""

from unittest import TestCase

from backend.models.journal import Journal, _strip_leaked_labels


class StripLeakedLabelsTest(TestCase):
    def test_removes_label_and_glued_title_without_newline(self):
        # 실사례: 라벨과 제목이 줄바꿈 없이 본문에 바로 이어붙은 경우
        title = "SK하이닉스, HBM 이후 '메모리 연산' 기술 검증"
        intro = (
            "기사 제목: SK하이닉스, HBM 이후 '메모리 연산' 기술 검증 "
            "SK하이닉스가 미국의 반도체 스타트업 테트라멤과 협력해, 메모리 내에서 "
            "직접 연산을 수행하는 혁신적인 AI 반도체 기술을 성공적으로 검증했다."
        )

        result = _strip_leaked_labels(intro, title)

        self.assertEqual(
            result,
            "SK하이닉스가 미국의 반도체 스타트업 테트라멤과 협력해, 메모리 내에서 "
            "직접 연산을 수행하는 혁신적인 AI 반도체 기술을 성공적으로 검증했다.",
        )

    def test_removes_label_and_title_with_blank_line(self):
        title = 'TXT 연준, 오늘 두 번째 미니앨범…"제 겉과 속 모두 담아"'
        intro = (
            '기사 제목: TXT 연준, 오늘 두 번째 미니앨범…"제 겉과 속 모두 담아"\n\n'
            "그룹 투모로우바이투게더(TXT)의 멤버 연준이 오늘 오후 1시 앨범을 발표한다."
        )

        result = _strip_leaked_labels(intro, title)

        self.assertEqual(
            result,
            "그룹 투모로우바이투게더(TXT)의 멤버 연준이 오늘 오후 1시 앨범을 발표한다.",
        )

    def test_title_casing_mismatch_is_still_stripped(self):
        # 화면에 보여주는 title 필드와 모델이 되뇐 텍스트의 영문 대소문자가
        # 다를 수 있어(예: "optimizers" vs "Optimizers") 대소문자 무시 비교로 처리한다.
        title = "Empathy for the optimizers"
        intro = (
            "기사 제목: Empathy for the Optimizers 이 기사는 최신 기술과 제품을 "
            "분석하고 논의하는 도구, 'Optimizer'에 대해 다룬다."
        )

        result = _strip_leaked_labels(intro, title)

        self.assertEqual(
            result,
            "이 기사는 최신 기술과 제품을 분석하고 논의하는 도구, 'Optimizer'에 대해 다룬다.",
        )

    def test_trailing_summary_label_is_also_removed(self):
        result = _strip_leaked_labels(
            "기사 제목: 제목\n기사 요약: 요약 텍스트\n실제 본문입니다.", "제목"
        )
        self.assertEqual(result, "실제 본문입니다.")

    def test_normal_text_without_leaked_label_is_untouched(self):
        text = "호텔가가 여름철을 맞아 보양식 출시와 함께 와인 페어링 메뉴를 강화했다."
        self.assertEqual(_strip_leaked_labels(text, "호텔가, 여름철 메뉴 개편"), text)

    def test_empty_or_none_text_passes_through(self):
        self.assertEqual(_strip_leaked_labels(""), "")
        self.assertIsNone(_strip_leaked_labels(None))


class JournalToDictTest(TestCase):
    def _make_journal(self, article_intros):
        journal = Journal()
        journal.date_label = "2026년 7월 10일"
        journal.headline = "테스트 헤드라인"
        journal.reflection = None
        journal.article_intros = article_intros
        journal.recommended_articles = None
        journal.music_text = None
        journal.music_tracks = None
        journal.schedule = None
        journal.keywords = None
        journal.photo_narrative = None
        journal.prompt_variants = None
        journal.created_at = None
        journal.updated_at = None
        return journal

    def test_to_dict_strips_leaked_label_from_article_intros(self):
        journal = self._make_journal(
            [
                {
                    "title": "SK하이닉스, HBM 이후 '메모리 연산' 기술 검증",
                    "link": "https://example.com/a",
                    "intro": (
                        "기사 제목: SK하이닉스, HBM 이후 '메모리 연산' 기술 검증 "
                        "SK하이닉스가 미국의 반도체 스타트업과 협력했다."
                    ),
                    "is_main": True,
                }
            ]
        )

        data = journal.to_dict()

        self.assertEqual(
            data["article_intros"][0]["intro"],
            "SK하이닉스가 미국의 반도체 스타트업과 협력했다.",
        )
        # title/link/is_main 등 나머지 필드는 그대로 보존돼야 함
        self.assertEqual(
            data["article_intros"][0]["title"],
            "SK하이닉스, HBM 이후 '메모리 연산' 기술 검증",
        )
        self.assertTrue(data["article_intros"][0]["is_main"])

    def test_to_dict_leaves_clean_article_intros_unchanged(self):
        journal = self._make_journal(
            [{"title": "제목", "link": "l", "intro": "정상적인 본문입니다.", "is_main": False}]
        )

        data = journal.to_dict()

        self.assertEqual(data["article_intros"][0]["intro"], "정상적인 본문입니다.")

    def test_to_dict_handles_missing_article_intros(self):
        journal = self._make_journal(None)

        data = journal.to_dict()

        self.assertIsNone(data["article_intros"])
