import React, { useState, useEffect, useRef, useLayoutEffect } from "react";
import { fetchJournal } from "./api/journal";
import { PHOTO_LIMITS, fetchPhotoObjectUrl, uploadPhotos } from "./api/photos";
import {
  initAuthFromUrl,
  isLoggedIn,
  logout,
  getAuthUser,
  startGoogleOAuthLogin,
} from "./auth";

/* ═════════════════════════════════════════════
   1. 메인 페이지 — 스트라이프 배경 + 빨간 우편함
═════════════════════════════════════════════ */

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

/* 오늘의 일정 박스 안 타임테이블 — 빈 칸으로 두고 손으로 채우는 용도 */
const TIMETABLE_PERIODS = [
  { label: "아침", hours: ["06:00", "07:00", "08:00", "09:00"] },
  { label: "오전", hours: ["10:00", "11:00", "12:00", "13:00"] },
  { label: "오후", hours: ["14:00", "15:00", "16:00", "17:00"] },
  { label: "저녁", hours: ["18:00", "19:00", "20:00", "21:00"] },
  { label: "밤", hours: ["22:00", "23:00", "00:00"] },
];

/* ═════════════════════════════════════════════
   재사용 메이슨리(균형 2단) 레이아웃
   — 각 박스를 실제 칼럼 너비로 먼저 렌더해서 높이를 재고,
     "지금 더 짧은 열"에 순서대로 넣어 두 열의 높이를 자동으로 맞춘다.
     기사가 들어오는 배치 우선순위(items 순서)는 유지하면서
     내용 길이가 매번 달라져도 빈 공간/깨짐 없이 정렬되게 하는 용도.
═════════════════════════════════════════════ */

function useElementWidth(ref) {
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect?.width;
      if (w) setWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return width;
}

function MasonryTwoCol({ items, gap = 32, resetKey }) {
  const containerRef = useRef(null);
  const measureRefs = useRef({});
  const width = useElementWidth(containerRef);
  const [columns, setColumns] = useState(null);
  const itemsKey = items.map((it) => it.key).join("|");
  const key = resetKey ?? itemsKey;

  // 날짜 이동 등으로 내용이 바뀌거나(resetKey) 칼럼 너비가 바뀌면 다시 잰다.
  useEffect(() => {
    setColumns(null);
  }, [key, width]);

  // 폰트 로딩이 늦게 끝나 실제 텍스트 높이가 달라질 수 있어 로딩 완료 후 한 번 더 잰다.
  useEffect(() => {
    if (!document.fonts?.ready) return;
    document.fonts.ready.then(() => setColumns(null));
  }, []);

  useLayoutEffect(() => {
    if (columns || !width) return;
    const heights = items.map((it) => measureRefs.current[it.key]?.offsetHeight ?? 0);
    if (heights.length === 0 || heights.some((h) => !h)) return;
    const colHeights = [0, 0];
    const colItems = [[], []];
    items.forEach((item, i) => {
      const target = colHeights[0] <= colHeights[1] ? 0 : 1;
      colItems[target].push(item);
      colHeights[target] += heights[i] + gap;
    });
    setColumns(colItems);
  });

  const colWidth = width ? (width - gap) / 2 : 0;
  const display = columns ?? [items, []];

  return (
    <div className="masonry-wrap" ref={containerRef}>
      {!columns && colWidth > 0 && (
        <div className="masonry-measure" style={{ width: colWidth }}>
          {items.map((item) => (
            <div key={item.key} ref={(el) => (measureRefs.current[item.key] = el)}>
              {item.node}
            </div>
          ))}
        </div>
      )}

      <div className="masonry-2col" style={{ gap }}>
        {display.map((col, ci) => (
          <div className="masonry-col" key={ci}>
            {col.map((item) => (
              <div className="masonry-item" key={item.key}>
                {item.node}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function formatBytes(bytes) {
  if (!bytes) return "0MB";
  return `${(bytes / 1024 / 1024).toFixed(bytes >= 1024 * 1024 ? 1 : 2)}MB`;
}

/* 인쇄 전용 레이아웃(PrintEdition)은 화면용 메이슨리처럼 내용 길이에 맞춰 늘어날 수 없고
   고정된 종이 크기 안에 들어가야 한다. journal_composer의 LLM 프롬프트가 글자수를
   가이드하긴 하지만(예: 메인기사 450~550자) 하드 제한은 아니라서, 혹시 넘치더라도
   물리적 페이지를 깨지 않도록 여기서 한 번 더 안전하게 잘라준다.
   (박스 높이는 이 소프트 가이드 기준 + 여유를 두고 잡았음 — 아래 PrintEdition 참고) */
function truncateText(text, maxLen) {
  if (!text) return "";
  const trimmed = text.trim();
  if (trimmed.length <= maxLen) return trimmed;
  return trimmed.slice(0, maxLen - 1).trimEnd() + "…";
}

function MailboxPhotoDrop() {
  const inputRef = useRef(null);
  const [files, setFiles] = useState([]);
  const [status, setStatus] = useState("idle");
  const [message, setMessage] = useState("");

  const totalSize = files.reduce((sum, file) => sum + file.size, 0);

  const chooseFiles = (event) => {
    const selected = Array.from(event.target.files ?? []);
    setStatus("idle");
    setMessage("");

    if (selected.length > PHOTO_LIMITS.maxFiles) {
      setFiles([]);
      setMessage(`한 번에 ${PHOTO_LIMITS.maxFiles}장까지만 투고할 수 있어요.`);
      return;
    }
    const oversized = selected.find((file) => file.size > PHOTO_LIMITS.maxFileSize);
    if (oversized) {
      setFiles([]);
      setMessage(`${oversized.name} 파일이 ${formatBytes(PHOTO_LIMITS.maxFileSize)}를 넘어요.`);
      return;
    }
    const selectedTotal = selected.reduce((sum, file) => sum + file.size, 0);
    if (selectedTotal > PHOTO_LIMITS.maxTotalSize) {
      setFiles([]);
      setMessage(`총 용량은 ${formatBytes(PHOTO_LIMITS.maxTotalSize)}까지만 가능해요.`);
      return;
    }
    setFiles(selected);
  };

  const submit = async () => {
    if (!files.length || status === "uploading") return;
    setStatus("uploading");
    setMessage("투고 중입니다...");
    try {
      const result = await uploadPhotos(files);
      const duplicates = result.results?.filter((item) => item.duplicate).length ?? 0;
      const accepted = (result.results?.length ?? 0) - duplicates;
      setStatus("done");
      setMessage(`투고 완료: 새 사진 ${accepted}장${duplicates ? `, 중복 ${duplicates}장` : ""}`);
      setFiles([]);
      if (inputRef.current) inputRef.current.value = "";
    } catch (error) {
      setStatus("error");
      setMessage(error.message || "업로드 실패. 다시 시도해주세요.");
    }
  };

  return (
    <section className="photo-drop">
      <div className="photo-drop-copy">
        <p className="photo-drop-kicker">TOMORROW EDITION</p>
        <h2>내일 조간 투고함</h2>
        <p>오늘의 사진과 스크린샷을 맡겨두면 내일 아침 신문에 반영됩니다.</p>
      </div>

      <div className="photo-drop-controls">
        <input
          ref={inputRef}
          className="photo-file-input"
          type="file"
          accept={PHOTO_LIMITS.accept}
          multiple
          onChange={chooseFiles}
        />
        <button
          className="photo-submit"
          type="button"
          disabled={!files.length || status === "uploading"}
          onClick={submit}
        >
          {status === "uploading" ? "투고 중" : "투고하기"}
        </button>
      </div>

      <div className="photo-drop-meta">
        <span>{files.length ? `${files.length}장 선택` : "사진을 선택하세요"}</span>
        <span>{formatBytes(totalSize)}</span>
      </div>
      {message && <p className={`photo-drop-message ${status}`}>{message}</p>}
    </section>
  );
}

function MailboxCalendar({ onSelectDate, onLogout }) {
  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth());

  const firstDay = new Date(year, month, 1).getDay();
  const lastDate = new Date(year, month + 1, 0).getDate();

  const prevMonth = () => {
    if (month === 0) { setYear(year - 1); setMonth(11); }
    else setMonth(month - 1);
  };
  const nextMonth = () => {
    if (month === 11) { setYear(year + 1); setMonth(0); }
    else setMonth(month + 1);
  };

  const cells = [
    ...Array(firstDay).fill(null),
    ...Array.from({ length: lastDate }, (_, i) => i + 1),
  ];

  const isToday = (d) =>
    d === today.getDate() &&
    month === today.getMonth() &&
    year === today.getFullYear();

  // 저널은 매일 "어제" 날짜 기준으로 생성되므로 오늘 날짜는 아직 열람할 수 없다.
  const todayStart = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const hasLetter = (d) => new Date(year, month, d) < todayStart;

  const pad = (n) => String(n).padStart(2, "0");

  return (
    <div className="stripe-bg">
      <header className="mail-header">
        <button className="mail-nav" onClick={prevMonth}>◂</button>
        <div className="mail-title">
          <span className="title-month-badge">
            <span className="title-month">{year}.{pad(month + 1)}</span>
          </span>
        </div>
        <button className="mail-nav" onClick={nextMonth}>▸</button>
      </header>

      <p className="mail-tagline">오늘의 기록이, 내일의 신문이 됩니다</p>

      <div className="mail-cabinet">
        <div className="mail-grid weekdays-row">
          {WEEKDAYS.map((w) => (
            <div key={w} className="mail-wd">{w}</div>
          ))}
        </div>

        <div className="mail-grid">
          {cells.map((d, i) =>
            d === null ? (
              <div key={`e-${i}`} className="mailbox blank" />
            ) : (
              <button
                key={d}
                className={`mailbox ${isToday(d) ? "today" : ""} ${!hasLetter(d) ? "future" : ""}`}
                disabled={!hasLetter(d)}
                title={!hasLetter(d) ? "아직 열람할 수 없어요" : undefined}
                onClick={() => {
                  if (!hasLetter(d)) return;
                  onSelectDate({ year, month, day: d });
                }}
              >
                {hasLetter(d) && (
                  <span className="letter">
                    <span className="letter-line" />
                    <span className="letter-line short" />
                  </span>
                )}
                <span className="slot" />
                <span className="num">{pad(d)}</span>
                <span className="door">
                  <span className="keyhole" />
                </span>
              </button>
            )
          )}
        </div>
      </div>

      <p className="mail-hint">우편함을 열어 그날의 신문을 꺼내 보세요</p>
      <MailboxPhotoDrop />
      {onLogout && (
        <button className="logout-link" onClick={onLogout}>
          로그아웃
        </button>
      )}
    </div>
  );
}

/* ═════════════════════════════════════════════
   1.5 인쇄 전용 레이아웃
   — 화면용 메이슨리/박스 CSS를 재사용하지 않고, A3 가로 한 장을 반으로 나눈
     고정 mm 크기 안에 맞춘 전용 마크업. 내용은 각 박스에 고정 높이를 주고,
     넘치는 텍스트는 truncateText로 안전하게 잘라 절대 페이지 밖으로 안 넘치게 함.
═════════════════════════════════════════════ */

// journal_composer.generate_music_section()이 Spotify 청취 기록이 없을 때 고정으로
// 내려주는 안내 문구. 인쇄판에서는 "데이터 없음"을 설명하는 문장 대신 그냥 빈칸으로
// 둔다(오늘 다짐 박스와 같은 취급).
const NO_MUSIC_TEXT = "어제 Spotify 청취 기록이 없어 음악 추천을 건너뜁니다.";

function PrintEdition({
  date,
  dateLabel,
  issueNo,
  paperTitle,
  journal,
  photoObjectUrl,
  mainArticle,
  sideArticleLeft,
  sideArticleRight,
  sideArticleBelowMain,
  reflectionTags,
  scheduleRows,
  scheduleByHour,
}) {
  const { day } = date;
  const hasTracks = journal?.music_tracks?.yesterday_top?.length > 0;
  const hasMusicText =
    !!journal?.music_text?.yesterday_text &&
    journal.music_text.yesterday_text !== NO_MUSIC_TEXT;
  // 추천할 음악 데이터가 아예 없으면(어제 청취 없음) 레코드판도 같이 숨긴다.
  const hasMusicData = hasTracks || hasMusicText;

  return (
    <div className="print-edition-wrap">
      <div className="print-sheet">
        {/* 1페이지: 마스트헤드 + 소제목 — 메인 기사(전문 한 박스) / 서브 기사1·2 / 날짜 */}
        <div className="print-page print-page-left">
          <div className="print-masthead">
            <div className="print-mast-topline">
              <span>No. {issueNo}</span>
              <span>{dateLabel}</span>
            </div>
            <h1 className="print-mast-title">{paperTitle}</h1>
            <div className="print-mast-rule" />
            <p className="print-mast-sub">{date.year} · MY PERSONAL ARCHIVE</p>
            <div className="print-mast-rule thin" />
          </div>

          <section className="print-today-comment">
            <p className="print-today-comment-text">
              {journal?.headline ? truncateText(journal.headline, 140) : ""}
            </p>
            {reflectionTags.length > 0 && (
              <div className="print-tag-row">
                {reflectionTags.map((tag) => (
                  <span className="print-tag-pill" key={tag}>
                    #{tag.replace(/\s+/g, "")}
                  </span>
                ))}
              </div>
            )}
          </section>

          <div className="print-row-main">
            {/* 왼쪽 칼럼: 메인 기사 + 4번째 기사(메인 바로 아래) */}
            <div className="print-col-main">
              <section className="print-box print-box-main">
                <h2 className="print-headline-title">
                  {mainArticle ? truncateText(mainArticle.title, 40) : ""}
                </h2>
                <p className="print-box-text">
                  {mainArticle ? truncateText(mainArticle.intro, 650) : ""}
                </p>
              </section>

              <section className="print-box">
                <h3 className="print-label">
                  {sideArticleBelowMain ? truncateText(sideArticleBelowMain.title, 30) : ""}
                </h3>
                <p className="print-box-text">
                  {sideArticleBelowMain
                    ? truncateText(sideArticleBelowMain.intro, 420)
                    : ""}
                </p>
              </section>
            </div>

            <div className="print-col-sub">
              <section className="print-box">
                <h3 className="print-label">
                  {sideArticleLeft ? truncateText(sideArticleLeft.title, 30) : ""}
                </h3>
                <p className="print-box-text">
                  {sideArticleLeft ? truncateText(sideArticleLeft.intro, 420) : ""}
                </p>
              </section>

              <section className="print-box">
                <h3 className="print-label">
                  {sideArticleRight ? truncateText(sideArticleRight.title, 30) : ""}
                </h3>
                <p className="print-box-text">
                  {sideArticleRight ? truncateText(sideArticleRight.intro, 420) : ""}
                </p>
              </section>
            </div>
          </div>

          <p className="print-page-footer-date">{dateLabel}</p>
        </div>

        {/* 2페이지: 오늘의 일정 / 사진 / 오늘 다짐 / 어제의 플레이리스트 — 2x2 동일 크기 그리드 */}
        <div className="print-page print-page-right">
          <div className="print-grid-2x2">
            <section className="print-box print-box-schedule">
              <h3 className="print-label">오늘의 일정</h3>
              <ul className="print-schedule-list">
                {scheduleRows.slice(0, 3).map((item, i) => (
                  <li key={i}>{truncateText(item, 26) || " "}</li>
                ))}
              </ul>
              <table className="print-timetable">
                <tbody>
                  {TIMETABLE_PERIODS.map((period) =>
                    period.hours.map((hour, hIdx) => (
                      <tr key={hour}>
                        {hIdx === 0 && (
                          <td className="print-tt-period" rowSpan={period.hours.length}>
                            {period.label}
                          </td>
                        )}
                        <td className="print-tt-hour">{hour}</td>
                        <td className="print-tt-cell">
                          {truncateText(scheduleByHour[hour] || "", 18)}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </section>

            <section className="print-box print-box-photo">
              {photoObjectUrl ? (
                <img className="print-photo-img" src={photoObjectUrl} alt="오늘의 사진" />
              ) : (
                <div
                  className="print-photo-img print-photo-placeholder"
                  style={{
                    background: `linear-gradient(150deg,
                      hsl(${(day * 37) % 360}, 18%, 62%),
                      hsl(${(day * 37 + 30) % 360}, 22%, 38%))`,
                  }}
                />
              )}
            </section>

            <section className="print-box print-box-pledge">
              <h3 className="print-label">오늘 다짐</h3>
              <div className="print-pledge-divider" />
            </section>

            <section className="print-box print-box-playlist">
              <h3 className="print-label">어제의 플레이리스트</h3>
              {/* 추천할 음악 데이터가 없으면 레코드판까지 통째로 숨기고 오늘 다짐처럼 빈 박스로 둠 */}
              {hasMusicData && (
                <div className="print-playlist-body">
                  <div className="print-vinyl">
                    <div className="print-vinyl-label">
                      <span>DAY</span>
                      <strong>{String(day).padStart(2, "0")}</strong>
                    </div>
                  </div>
                  <div className="print-playlist-text">
                    <p className="print-box-text">
                      {hasMusicText ? truncateText(journal.music_text.yesterday_text, 120) : ""}
                    </p>
                    {hasTracks && (
                      <ul className="print-playlist-list">
                        {journal.music_tracks.yesterday_top.slice(0, 4).map((t, i) => (
                          <li key={i}>{truncateText(`${t.title} — ${t.artist}`, 30)}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              )}
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ═════════════════════════════════════════════
   2. 날짜별 페이지 — 신문 컨셉
═════════════════════════════════════════════ */

function NewspaperPage({ date, onBack, autoPrint = false }) {
  const { year, month, day } = date;
  const d = new Date(year, month, day);
  const weekday = WEEKDAYS[d.getDay()];
  const dateLabel = `${year}년 ${month + 1}월 ${day}일 ${weekday}요일`;
  const issueNo = Math.floor((d - new Date(year, 0, 1)) / 86400000) + 1;

  const pad2 = (n) => String(n).padStart(2, "0");
  const targetDate = `${year}-${pad2(month + 1)}-${pad2(day)}`;

  /* ★ 날짜별 데이터 연결 지점
     journal 안에 headline / reflection / article_intros / recommended_articles /
     music_text / music_tracks / schedule / keywords / photo_narrative 들어있음. */
  const [journal, setJournal] = useState(null);
  const [journalError, setJournalError] = useState(null);
  const [journalLoaded, setJournalLoaded] = useState(false);
  const [photoObjectUrl, setPhotoObjectUrl] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setJournal(null);
    setJournalError(null);
    setJournalLoaded(false);
    setPhotoObjectUrl(null);
    if (typeof document !== "undefined") {
      document.body.removeAttribute("data-print-ready");
    }

    fetchJournal(targetDate)
      .then((data) => {
        if (cancelled) return;
        setJournal(data);
        console.log("[journal]", targetDate, data);
      })
      .catch((err) => {
        if (cancelled) return;
        setJournalError(err.message);
        console.error("[journal] fetch failed:", err);
      })
      .finally(() => {
        if (!cancelled) setJournalLoaded(true);
      });

    return () => {
      cancelled = true;
    };
  }, [targetDate]);

  // 자동 인쇄(Playwright)용 신호: 저널 + 사진까지 다 실려서 화면이 안정된 뒤
  // body[data-print-ready="true"]를 세팅. 헤드리스 브라우저가 이걸 보고 PDF로 캡처.
  useEffect(() => {
    if (!journalLoaded || typeof document === "undefined") return;
    const needsPhoto = Boolean(journal?.photo?.id);
    if (needsPhoto && !photoObjectUrl) return;
    const timer = setTimeout(() => {
      document.body.setAttribute("data-print-ready", "true");
    }, 500);
    return () => clearTimeout(timer);
  }, [journalLoaded, journal, photoObjectUrl]);

  useEffect(() => {
    let cancelled = false;
    let objectUrl = null;
    setPhotoObjectUrl(null);

    if (!journal?.photo?.id) {
      return () => {};
    }

    fetchPhotoObjectUrl(journal.photo.id)
      .then((url) => {
        objectUrl = url;
        if (!cancelled) setPhotoObjectUrl(url);
      })
      .catch((err) => {
        if (!cancelled) console.error("[photo] fetch failed:", err);
      });

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [journal?.photo?.id]);

  // journal 필드 → 신문 레이아웃 매핑
  const mainArticle = journal?.article_intros?.find((a) => a.is_main) ?? null;
  const sideArticles = journal?.article_intros?.filter((a) => !a.is_main) ?? [];
  const sideArticleLeft = sideArticles[0] ?? null;
  const sideArticleRight = sideArticles[1] ?? null;
  // 4번째 기사 — 인쇄판에서는 메인 기사 바로 아래(왼쪽 칼럼)에 배치.
  const sideArticleBelowMain = sideArticles[2] ?? null;
  const reflectionTags = journal?.reflection
    ? journal.reflection
        .split("/")
        .map((t) => t.trim())
        .filter(Boolean)
    : [];

  // schedule는 텍스트 한 덩어리로 옴 — 줄바꿈/쉼표/가운뎃점 기준으로 나눠서 목록화.
  // "HH:MM 제목" 형식의 실제 일정은 타임테이블의 해당 시간 칸에 직접 표시하고,
  // 위쪽 목록은 사용자가 손으로 직접 적는 메모용으로 항상 3줄 고정.
  const scheduleText = journal?.schedule?.trim() ?? "";
  const scheduleItems =
    scheduleText && scheduleText !== "일정 없음"
      ? scheduleText
          .split(/\n|,|·/)
          .map((s) => s.trim())
          .filter(Boolean)
      : [];
  const scheduleByHour = {};
  scheduleItems.forEach((item) => {
    const match = item.match(/^(\d{1,2}):(\d{2})\s*(.*)$/);
    if (!match) return;
    const hourKey = `${match[1].padStart(2, "0")}:00`;
    const text = match[3].trim();
    if (!text) return;
    scheduleByHour[hourKey] = scheduleByHour[hourKey]
      ? `${scheduleByHour[hourKey]}, ${text}`
      : text;
  });
  const scheduleRows = ["", "", ""];

  // 신문 이름 — 매번 새로 정할 수 있게 클릭해서 수정, 마지막 값은 기억해둠.
  const [paperTitle, setPaperTitle] = useState(
    () => localStorage.getItem("paperback_paper_title") || "The Daily Record"
  );
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState(paperTitle);

  const startEditTitle = () => {
    setTitleDraft(paperTitle);
    setEditingTitle(true);
  };
  const saveTitle = () => {
    const next = titleDraft.trim() || "The Daily Record";
    setPaperTitle(next);
    localStorage.setItem("paperback_paper_title", next);
    setEditingTitle(false);
  };

  // 인쇄 전용 화면(PrintEdition) 표시 여부.
  // 수동: "인쇄하기" 버튼 클릭 시 켜짐. 자동: ?print_date로 들어온 경우(autoPrint) 처음부터 켜짐.
  const [printMode, setPrintMode] = useState(autoPrint);

  useEffect(() => {
    if (!printMode || typeof window === "undefined") return;
    if (autoPrint) return; // 자동 인쇄 파이프라인은 헤드리스에서 PDF만 캡처하면 됨 — window.print() 불필요
    const frame = requestAnimationFrame(() => window.print());
    const handleAfterPrint = () => setPrintMode(false);
    window.addEventListener("afterprint", handleAfterPrint);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("afterprint", handleAfterPrint);
    };
  }, [printMode, autoPrint]);

  if (printMode) {
    return (
      <>
        <PrintEdition
          date={date}
          dateLabel={dateLabel}
          issueNo={issueNo}
          paperTitle={paperTitle}
          journal={journal}
          photoObjectUrl={photoObjectUrl}
          mainArticle={mainArticle}
          sideArticleLeft={sideArticleLeft}
          sideArticleRight={sideArticleRight}
          sideArticleBelowMain={sideArticleBelowMain}
          reflectionTags={reflectionTags}
          scheduleRows={scheduleRows}
          scheduleByHour={scheduleByHour}
        />
        {!autoPrint && (
          <div className="page-actions">
            <button className="back-btn" onClick={() => setPrintMode(false)}>
              ← 미리보기 닫기
            </button>
            <button className="print-btn" onClick={() => window.print()}>
              🖨 인쇄
            </button>
          </div>
        )}
      </>
    );
  }

  return (
    <div className="news-bg">
      <div className="paper-sheet">
        <div className="front-page">
        <header className="masthead">
          <div className="mast-topline">
            <span>No. {issueNo}</span>
            <span>{dateLabel}</span>
            <span>DAILY EDITION</span>
          </div>
          {editingTitle ? (
            <input
              className="mast-title-input"
              value={titleDraft}
              autoFocus
              onChange={(e) => setTitleDraft(e.target.value)}
              onBlur={saveTitle}
              onKeyDown={(e) => {
                if (e.key === "Enter") saveTitle();
                if (e.key === "Escape") setEditingTitle(false);
              }}
            />
          ) : (
            <h1
              className="mast-title"
              onClick={startEditTitle}
              title="클릭해서 신문 이름 수정"
            >
              {paperTitle}
            </h1>
          )}
          <div className="mast-rule" />
          <p className="mast-sub">{year} · MY PERSONAL ARCHIVE</p>
          <div className="mast-rule thin" />
        </header>

        <section className="today-comment">
          <p className="today-comment-text">
            {journal?.headline || "오늘 하루를 대표하는 한 줄이 아직 없어요."}
          </p>
          {reflectionTags.length > 0 && (
            <div className="tag-row">
              {reflectionTags.map((tag) => (
                <span className="tag-pill" key={tag}>
                  #{tag.replace(/\s+/g, "")}
                </span>
              ))}
            </div>
          )}
        </section>

        <MasonryTwoCol
          resetKey={`${targetDate}-top-${journal ? "loaded" : "loading"}-${photoObjectUrl ? "photo" : "placeholder"}`}
          items={[
            {
              key: "headline",
              node: (
                <section className="box box-headline">
                  <h2 className="headline">
                    {mainArticle ? mainArticle.title : "Headline of the Day"}
                  </h2>
                  <p className="col-text">
                    {mainArticle
                      ? mainArticle.intro
                      : "가운데 컬럼은 그날의 가장 큰 사건을 다루는 헤드라인 영역입니다. 사진 한 장과 짧은 기사 — 이것만으로도 하루가 충분히 기록됩니다."}
                  </p>
                  {mainArticle?.link && (
                    <a
                      className="source-link"
                      href={mainArticle.link}
                      target="_blank"
                      rel="noreferrer"
                    >
                      원문 보기 ↗
                    </a>
                  )}
                </section>
              ),
            },
            {
              key: "photo",
              node: (
                <section className="box photo-box">
                  <h3 className="label">오늘의 사진</h3>
                  <figure className="news-photo">
                    {photoObjectUrl ? (
                      <img
                        className="photo-area photo-image"
                        src={photoObjectUrl}
                        alt={journal?.photo?.filename || "오늘의 사진"}
                      />
                    ) : (
                      <div
                        className="photo-area"
                        style={{
                          background: `linear-gradient(150deg,
                            hsl(${(day * 37) % 360}, 18%, 62%),
                            hsl(${(day * 37 + 30) % 360}, 22%, 38%))`,
                        }}
                      />
                    )}
                  </figure>
                </section>
              ),
            },
            {
              key: "schedule",
              node: (
                <section className="box">
                  <h3 className="label underline">오늘의 일정</h3>
                  <ul className="schedule-list">
                    {scheduleRows.map((item, i) => (
                      <li key={i}>{item || " "}</li>
                    ))}
                  </ul>
                  <div className="timetable-box">
                    <table className="timetable">
                      <tbody>
                        {TIMETABLE_PERIODS.map((period) =>
                          period.hours.map((hour, hIdx) => (
                            <tr key={hour}>
                              {hIdx === 0 && (
                                <td className="tt-period" rowSpan={period.hours.length}>
                                  {period.label}
                                </td>
                              )}
                              <td className="tt-hour">{hour}</td>
                              <td className="tt-cell">{scheduleByHour[hour] || ""}</td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </section>
              ),
            },
            {
              key: "side-left",
              node: (
                <section className="box">
                  <h3 className="label">
                    {sideArticleLeft ? sideArticleLeft.title : "사이드 기사"}
                  </h3>
                  {sideArticleLeft ? (
                    <>
                      <p className="col-text">{sideArticleLeft.intro}</p>
                      {sideArticleLeft.link && (
                        <a
                          className="source-link"
                          href={sideArticleLeft.link}
                          target="_blank"
                          rel="noreferrer"
                        >
                          원문 보기 ↗
                        </a>
                      )}
                    </>
                  ) : (
                    <p className="col-text">
                      하루의 전반부 기록이 들어가는 칼럼입니다. 나중에 날짜별
                      데이터를 연결하면 이 칼럼이 그날의 이야기로 채워집니다.
                    </p>
                  )}
                </section>
              ),
            },
          ]}
        />
        </div>

        <div className="back-page">
        <MasonryTwoCol
          resetKey={`${targetDate}-bottom-${journal ? "loaded" : "loading"}`}
          items={[
            {
              key: "side-right",
              node: (
                <section className="box">
                  <h3 className="label">
                    {sideArticleRight ? sideArticleRight.title : "사이드 기사"}
                  </h3>
                  {sideArticleRight ? (
                    <>
                      <p className="col-text">{sideArticleRight.intro}</p>
                      {sideArticleRight.link && (
                        <a
                          className="source-link"
                          href={sideArticleRight.link}
                          target="_blank"
                          rel="noreferrer"
                        >
                          원문 보기 ↗
                        </a>
                      )}
                    </>
                  ) : (
                    <p className="col-text">
                      하루의 후반부 기록. 저녁에 있었던 일이나 하루를 마치며
                      든 생각을 적는 칼럼입니다.
                    </p>
                  )}
                </section>
              ),
            },
            {
              key: "side-below-main",
              node: (
                <section className="box">
                  <h3 className="label">
                    {sideArticleBelowMain ? sideArticleBelowMain.title : "사이드 기사"}
                  </h3>
                  {sideArticleBelowMain ? (
                    <>
                      <p className="col-text">{sideArticleBelowMain.intro}</p>
                      {sideArticleBelowMain.link && (
                        <a
                          className="source-link"
                          href={sideArticleBelowMain.link}
                          target="_blank"
                          rel="noreferrer"
                        >
                          원문 보기 ↗
                        </a>
                      )}
                    </>
                  ) : (
                    <p className="col-text">
                      네 번째 기사 칼럼입니다. 날짜별 데이터를 연결하면 이 칼럼이
                      그날의 이야기로 채워집니다.
                    </p>
                  )}
                </section>
              ),
            },
            {
              key: "pledge",
              node: (
                <section className="box box-pledge">
                  <h3 className="label">하루다짐</h3>
                  <div className="pledge-divider" />
                </section>
              ),
            },
          ]}
        />

        <footer className="news-footer" style={{ marginTop: 8 }}>
          <div className="vinyl">
            <div className="vinyl-label">
              <span>DAY</span>
              <strong>{String(day).padStart(2, "0")}</strong>
            </div>
          </div>
          <div className="footer-text">
            <h3 className="label underline">어제의 플레이리스트</h3>
            <p className="col-text">
              {journal?.music_text?.yesterday_text ||
                "하루를 닫는 한 줄. 레코드판 라벨의 숫자는 날짜와 함께 바뀝니다."}
            </p>
            {journal?.music_tracks?.yesterday_top?.length > 0 && (
              <ul className="playlist-list">
                {journal.music_tracks.yesterday_top.map((t, i) => (
                  <li key={i}>
                    {t.title} — {t.artist}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </footer>
        </div>
      </div>

      <div className="page-actions">
        <button className="back-btn" onClick={onBack}>← 우편함으로</button>
        <button className="print-btn" onClick={() => setPrintMode(true)}>🖨 인쇄하기</button>
      </div>
    </div>
  );
}

/* ═════════════════════════════════════════════
   0. 로그인 화면 (목업)
   — 실제 Google OAuth가 백엔드에 연결되면 onLogin만 realGoogleLogin으로 교체.
═════════════════════════════════════════════ */

function LoginScreen({ onLogin }) {
  return (
    <div className="login-bg">
      <div className="login-card">
        <p className="login-kicker">PAPERBACK AGENT</p>
        <h1 className="login-title">우편함 열쇠가 필요해요</h1>
        <p className="login-desc">
          Google 계정으로 한 번만 로그인하면,
          <br />
          다음부터는 자동으로 우편함이 열립니다.
        </p>
        <button className="login-google-btn" onClick={onLogin}>
          <span className="login-google-icon">G</span>
          Google OAuth로 로그인
        </button>
        <p className="login-hint">저널 수집에 쓰는 계정으로 로그인해야 기록을 볼 수 있습니다.</p>
      </div>
    </div>
  );
}

/* ═════════════════════════════════════════════
   앱 루트
═════════════════════════════════════════════ */

// test/main.jsx가 로그인 없이 바로 우편함부터 테스트할 수 있도록 컴포넌트를
// 그대로 재사용한다. 실제 배포 진입점(src/index.jsx)은 아래 default export(App)를
// 쓰고, 테스트 진입점은 이 named export들을 써서 같은 소스를 공유한다.
export { MailboxCalendar, NewspaperPage, css };

export default function App() {
  const [selectedDate, setSelectedDate] = useState(null);
  const [loggedIn, setLoggedIn] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);
  const [autoPrint, setAutoPrint] = useState(false);
  const authUser = getAuthUser();

  useEffect(() => {
    initAuthFromUrl(); // 백엔드가 ?token=... 을 붙여 리다이렉트해오면 여기서 저장됨
    setLoggedIn(isLoggedIn());
    setAuthChecked(true);

    // 자동 인쇄 파이프라인용: ?print_date=YYYY-MM-DD 로 들어오면
    // 우편함 화면을 거치지 않고 바로 해당 날짜의 인쇄 전용 화면(PrintEdition)으로 진입.
    const printDate = new URL(window.location.href).searchParams.get("print_date");
    if (printDate) {
      const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(printDate);
      if (match) {
        const [, y, m, d] = match;
        setSelectedDate({ year: Number(y), month: Number(m) - 1, day: Number(d) });
        setAutoPrint(true);
      }
    }
  }, []);

  if (!authChecked) return null;

  if (!loggedIn) {
    return (
      <>
        <style>{css}</style>
        <LoginScreen
          onLogin={async () => {
            await startGoogleOAuthLogin();
          }}
        />
        <ScrollNudge />
      </>
    );
  }

  return (
    <>
      <style>{css}</style>
      {authUser?.id ? (
        <div className="auth-badge">로그인됨 · user {authUser.id}</div>
      ) : null}
      {selectedDate === null ? (
        <MailboxCalendar
          onSelectDate={setSelectedDate}
          onLogout={() => {
            logout();
            setLoggedIn(false);
          }}
        />
      ) : (
        <NewspaperPage
          date={selectedDate}
          onBack={() => setSelectedDate(null)}
          autoPrint={autoPrint}
        />
      )}
      <ScrollNudge />
    </>
  );
}

/* ═════════════════════════════════════════════
   Dacon 코드공유 등 iframe 임베드에서 마우스 휠/트랙패드 스크롤이
   막히는 경우를 위한 우회용 스크롤 버튼.
   window.scrollBy는 스크립트로 직접 스크롤 위치를 옮기는 것이라
   휠 이벤트가 막힌 상황에서도 동작할 가능성이 있음.
═════════════════════════════════════════════ */
function ScrollNudge() {
  const scrollBy = (amount) => {
    window.scrollBy({ top: amount, behavior: "smooth" });
  };
  const scrollToEdge = (edge) => {
    const target = edge === "top" ? 0 : document.documentElement.scrollHeight;
    window.scrollTo({ top: target, behavior: "smooth" });
  };
  return (
    <div className="scroll-nudge" aria-hidden={false}>
      <button
        type="button"
        className="scroll-nudge-btn"
        onClick={() => scrollToEdge("top")}
        onDoubleClick={() => scrollToEdge("top")}
        title="맨 위로"
        aria-label="맨 위로 스크롤"
      >
        ▲▲
      </button>
      <button
        type="button"
        className="scroll-nudge-btn"
        onClick={() => scrollBy(-400)}
        title="위로"
        aria-label="위로 스크롤"
      >
        ▲
      </button>
      <button
        type="button"
        className="scroll-nudge-btn"
        onClick={() => scrollBy(400)}
        title="아래로"
        aria-label="아래로 스크롤"
      >
        ▼
      </button>
      <button
        type="button"
        className="scroll-nudge-btn"
        onClick={() => scrollToEdge("bottom")}
        onDoubleClick={() => scrollToEdge("bottom")}
        title="맨 아래로"
        aria-label="맨 아래로 스크롤"
      >
        ▼▼
      </button>
    </div>
  );
}

/* ═════════════════════════════════════════════
   스타일
═════════════════════════════════════════════ */

/* 필름 그레인용 노이즈 (SVG를 data URI로 내장) */
const NOISE = `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='300' height='300'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")`;

/* 흰 벽돌 벽 패턴 (SVG를 data URI로 내장, 80x40 타일 반복) */
const BRICK = `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='80' height='40'%3E%3Crect width='80' height='40' fill='%23f2ede4'/%3E%3Crect x='1' y='1' width='38' height='18' fill='%23fdfcfa' stroke='%23e6e0d3' stroke-width='1'/%3E%3Crect x='41' y='1' width='38' height='18' fill='%23fdfcfa' stroke='%23e6e0d3' stroke-width='1'/%3E%3Crect x='-19' y='21' width='38' height='18' fill='%23fdfcfa' stroke='%23e6e0d3' stroke-width='1'/%3E%3Crect x='21' y='21' width='38' height='18' fill='%23fdfcfa' stroke='%23e6e0d3' stroke-width='1'/%3E%3Crect x='61' y='21' width='38' height='18' fill='%23fdfcfa' stroke='%23e6e0d3' stroke-width='1'/%3E%3C/svg%3E")`;

const css = `
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,700;0,900;1,600&family=Nanum+Myeongjo:wght@400;700;800&family=Noto+Sans+KR:wght@400;500&family=Bangers&display=swap');

:root {
  /* Pantone 18-1659 TCX "Goji Berry" 기준, 채도 살짝 올림 */
  --red-deep: #980c1d;
  --red-box:  #be0f24;
  --red-hi:   #df3441;
  /* 뉴트럴 그레이 (블루 톤 제거, 밝기 업) */
  --cream:    #EAEAE8;
  --ink:      #262626;
  --rule:     #2f2f2f;
  --grey-mid: #DAD9D5;
  --grey-deep:#B9B8B2;
}

* { box-sizing: border-box; margin: 0; }
body { min-height: 100vh; }

/* ═══ 흰 벽돌 벽 배경 ═══ */
.stripe-bg {
  min-height: 100vh;
  position: relative;
  background-color: #f2ede4;
  background-image: ${BRICK};
  background-size: 80px 40px;
  padding: 44px 20px 60px;
  font-family: 'Noto Sans KR', sans-serif;
  display: flex;
  flex-direction: column;
  align-items: center;
}
/* 배경 전체에 필름 그레인(은은하게) + 비네팅(가장자리 어둡게) */
.stripe-bg::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background-image: ${NOISE};
  opacity: 0.25;
  mix-blend-mode: multiply;
  z-index: 3;
}
.stripe-bg::after {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background: radial-gradient(120% 90% at 50% 35%,
    transparent 55%, rgba(60,50,40,0.22) 100%);
  z-index: 2;
}
.stripe-bg > * { position: relative; z-index: 4; }

.mail-header {
  display: flex;
  align-items: center;
  gap: 22px;
  margin-bottom: 26px;
}
.mail-title { text-align: center; color: #4a453f; }
.title-month-badge {
  display: inline-block;
}
.title-month {
  display: inline-block;
  font-family: 'Bangers', cursive;
  font-size: 72px;
  letter-spacing: 3px;
  color: var(--red-box);
  -webkit-text-stroke: 2px #2a251c;
  text-shadow: 3px 3px 0 #2a251c, 4px 4px 6px rgba(0,0,0,0.3);
  line-height: 1;
}
.mail-nav {
  background: #faf8f2;
  border: 1px solid #b5afa4;
  border-radius: 2px;
  color: #4a453f;
  width: 38px; height: 38px;
  font-size: 18px;
  cursor: pointer;
  box-shadow: 0 1px 2px rgba(0,0,0,0.15);
}
.mail-nav:hover { border-color: var(--red-box); color: var(--red-box); }

.mail-tagline {
  font-family: 'Nanum Myeongjo', serif;
  font-style: italic;
  font-size: 14px;
  letter-spacing: 1px;
  color: #8c8578;
  margin: -10px 0 26px;
  text-align: center;
}

/* ═══ 빨간 우편함 캐비닛 ═══ */
.mail-cabinet {
  position: relative;
  background:
    /* 위에서 비스듬히 떨어지는 조명 */
    linear-gradient(115deg, rgba(255,255,255,0.06) 0%, transparent 30%, rgba(0,0,0,0.18) 100%),
    linear-gradient(180deg, var(--red-hi) 0%, var(--red-box) 45%, var(--red-deep) 100%);
  border-radius: 3px;
  padding: 18px 16px 16px;
  box-shadow:
    0 24px 44px rgba(50, 15, 15, 0.42),
    0 6px 12px rgba(0,0,0,0.28),
    inset 0 1px 0 rgba(255,255,255,0.14),
    inset 0 -2px 4px rgba(0,0,0,0.35);
  width: 100%;
  max-width: 700px;
  overflow: hidden;
}
/* 금속 표면 거칠기: 노이즈를 오버레이로 */
.mail-cabinet::before {
  content: "";
  position: absolute;
  inset: 0;
  background-image: ${NOISE};
  opacity: 0.35;
  mix-blend-mode: overlay;
  pointer-events: none;
  z-index: 5;
}
/* 유리에 반사된 듯한 사선 광 */
.mail-cabinet::after {
  content: "";
  position: absolute;
  top: -30%;
  left: -10%;
  width: 45%;
  height: 160%;
  background: linear-gradient(100deg,
    transparent 20%, rgba(255,255,255,0.05) 45%,
    rgba(255,255,255,0.09) 50%, rgba(255,255,255,0.05) 55%, transparent 80%);
  transform: rotate(4deg);
  pointer-events: none;
  z-index: 4;
}

.mail-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 2px;
  position: relative;
}
.weekdays-row { margin-bottom: 8px; }
.mail-wd {
  text-align: center;
  color: rgba(240,230,215,0.55);
  font-size: 11px;
  letter-spacing: 3px;
  padding: 3px 0;
  text-shadow: 0 1px 1px rgba(0,0,0,0.5);
}

/* 우편함 한 칸 */
.mailbox {
  position: relative;
  aspect-ratio: 4 / 5;
  background:
    linear-gradient(168deg, rgba(255,255,255,0.05) 0%, transparent 28%),
    linear-gradient(180deg, var(--red-hi), var(--red-box) 55%, #8a1220);
  border: 1px solid rgba(15,3,3,0.55);
  border-top-color: rgba(255,255,255,0.13);
  border-left-color: rgba(255,255,255,0.05);
  padding: 0;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
  color: #ece2d0;
  transition: filter 0.12s;
}
/* 칸마다 미묘하게 다른 밝기/색조 — 균일함 깨기 */
.mailbox:nth-child(3n)  { filter: brightness(0.96); }
.mailbox:nth-child(5n)  { filter: brightness(1.04) saturate(0.95); }
.mailbox:nth-child(7n)  { filter: brightness(0.93) hue-rotate(-2deg); }
.mailbox:nth-child(11n) { filter: brightness(1.06); }

.mailbox:hover { filter: brightness(1.18); }
.mailbox.blank {
  background: linear-gradient(180deg, #430c0d, #390a0b);
  border-color: rgba(0,0,0,0.4);
  cursor: default;
  pointer-events: none;
}
.mailbox.today {
  box-shadow: inset 0 0 0 1.5px rgba(240,230,210,0.75);
}
.mailbox.future,
.mailbox:disabled {
  cursor: not-allowed;
}
.mailbox.future:hover,
.mailbox:disabled:hover {
  filter: none;
}

.slot {
  width: 62%;
  height: 8%;
  min-height: 6px;
  background: linear-gradient(180deg, #0d0202 30%, #241010);
  border-radius: 1px;
  box-shadow:
    inset 0 3px 4px rgba(0,0,0,0.95),
    0 1px 0 rgba(255,255,255,0.10);
  margin-top: 12%;
  position: relative;
  z-index: 2;
}
.num {
  font-weight: 500;
  font-size: clamp(13px, 2vw, 19px);
  letter-spacing: 1px;
  margin: 8% 0 6%;
  text-shadow: 0 1px 2px rgba(0,0,0,0.6);
  opacity: 0.92;
}
.door {
  width: 62%;
  flex: 1;
  margin-bottom: 12%;
  background: linear-gradient(180deg, rgba(255,255,255,0.05), rgba(0,0,0,0.22));
  border: 1px solid rgba(10,2,2,0.5);
  border-top-color: rgba(255,255,255,0.08);
  display: flex;
  justify-content: center;
  padding-top: 14%;
}
.keyhole {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: radial-gradient(circle at 32% 28%, #d8c79b, #6b5a33 55%, #241c0c);
  box-shadow:
    0 1px 2px rgba(0,0,0,0.9),
    inset 0 -1px 1px rgba(0,0,0,0.6);
}

/* 투입구에 꽂힌 편지 */
.letter {
  position: absolute;
  top: -9%;
  left: 24%;
  width: 52%;
  height: 20%;
  background:
    linear-gradient(94deg, rgba(0,0,0,0.05), transparent 40%),
    linear-gradient(180deg, #fbf9f3, #e8e3d5);
  border: 1px solid #c2bbaa;
  border-bottom: none;
  border-radius: 1px 2px 0 0;
  box-shadow:
    -2px -2px 5px rgba(0,0,0,0.28),
    1px 0 2px rgba(0,0,0,0.15);
  transform: rotate(-5deg);
  transform-origin: bottom center;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  transition: transform 0.15s;
}
.mailbox:hover .letter { transform: rotate(-5deg) translateY(-3px); }
.letter-line { width: 55%; height: 1.5px; background: #a49c8b; opacity: 0.8; }
.letter-line.short { width: 35%; }

.mail-hint {
  margin-top: 26px;
  color: #7d786f;
  font-size: 13px;
  letter-spacing: 2px;
}
.photo-drop {
  width: 100%;
  max-width: 700px;
  margin-top: 24px;
  padding: 18px 18px 16px;
  border: 1px solid #d8d2c4;
  background: rgba(253,252,250,0.9);
  box-shadow: 0 8px 20px rgba(50,15,15,0.08);
}
.photo-drop-copy {
  text-align: left;
}
.photo-drop-kicker {
  margin-bottom: 6px;
  color: var(--red-box);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 3px;
}
.photo-drop h2 {
  font-family: 'Nanum Myeongjo', serif;
  font-size: 20px;
  font-weight: 800;
  color: #211c14;
  margin-bottom: 8px;
}
.photo-drop-copy p:last-child {
  color: #5c574c;
  font-size: 13px;
  line-height: 1.6;
}
.photo-drop-controls {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-top: 14px;
}
.photo-file-input {
  flex: 1;
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid #c7c1b4;
  background: #fff;
  color: #3c352c;
  font-size: 12px;
}
.photo-submit {
  min-width: 92px;
  padding: 10px 14px;
  border: none;
  background: var(--ink);
  color: var(--cream);
  font-size: 12px;
  letter-spacing: 1px;
  cursor: pointer;
}
.photo-submit:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}
.photo-drop-meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-top: 9px;
  color: #8c8578;
  font-size: 11px;
}
.photo-drop-message {
  margin-top: 10px;
  font-size: 12px;
  line-height: 1.5;
  color: #5c574c;
}
.photo-drop-message.done { color: #356847; }
.photo-drop-message.error { color: var(--red-box); }
.logout-link {
  margin-top: 10px;
  background: none;
  border: none;
  color: #a49c8b;
  font-size: 12px;
  letter-spacing: 1px;
  text-decoration: underline;
  text-underline-offset: 3px;
  cursor: pointer;
}
.logout-link:hover { color: var(--red-box); }
.auth-badge {
  position: fixed;
  top: 14px;
  right: 14px;
  z-index: 10;
  padding: 8px 12px;
  border: 1px solid rgba(38, 38, 38, 0.12);
  border-radius: 999px;
  background: rgba(250, 248, 243, 0.9);
  color: #4f473d;
  font-size: 12px;
  letter-spacing: 0.2px;
  backdrop-filter: blur(8px);
}

/* ═══ 스크롤 우회 버튼 (iframe 임베드용) ═══ */
.scroll-nudge {
  position: fixed;
  right: 16px;
  bottom: 16px;
  z-index: 99999;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.scroll-nudge-btn {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  border: none;
  background: rgba(24, 22, 20, 0.82);
  color: #fdfcfa;
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.3);
  transition: background 0.15s ease, transform 0.1s ease;
}
.scroll-nudge-btn:hover {
  background: rgba(24, 22, 20, 0.95);
}
.scroll-nudge-btn:active {
  transform: scale(0.92);
}

/* ═══ 로그인 화면 ═══ */
.login-bg {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: #f2ede4;
  background-image: ${BRICK};
  background-size: 80px 40px;
  padding: 20px;
  font-family: 'Noto Sans KR', sans-serif;
}
.login-card {
  width: 100%;
  max-width: 380px;
  background: #fdfcfa;
  border: 1px solid #d8d2c4;
  border-radius: 6px;
  padding: 40px 32px 32px;
  text-align: center;
  box-shadow:
    0 24px 44px rgba(50, 15, 15, 0.18),
    0 6px 12px rgba(0,0,0,0.08);
}
.login-kicker {
  font-size: 11px;
  letter-spacing: 4px;
  color: var(--red-box);
  font-weight: 700;
  margin-bottom: 14px;
}
.login-title {
  font-family: 'Nanum Myeongjo', serif;
  font-size: 22px;
  font-weight: 800;
  color: #211c14;
  margin-bottom: 14px;
}
.login-desc {
  font-size: 13px;
  line-height: 1.7;
  color: #5c574c;
  margin-bottom: 26px;
}
.login-google-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  width: 100%;
  padding: 12px 16px;
  font-family: 'Noto Sans KR', sans-serif;
  font-size: 14px;
  font-weight: 500;
  color: #262626;
  background: #fff;
  border: 1px solid #c7c1b4;
  border-radius: 3px;
  cursor: pointer;
  transition: box-shadow 0.12s, border-color 0.12s;
}
.login-google-btn:hover {
  border-color: var(--red-box);
  box-shadow: 0 2px 8px rgba(190, 15, 36, 0.15);
}
.login-google-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px; height: 18px;
  border-radius: 50%;
  background: var(--red-box);
  color: #fff;
  font-size: 12px;
  font-weight: 800;
}
.login-hint {
  margin-top: 18px;
  font-size: 11px;
  letter-spacing: 0.5px;
  color: #b0aa9c;
}

/* ═══ 신문 페이지 ═══ */
.news-bg {
  min-height: 100vh;
  background:
    radial-gradient(110% 90% at 50% 30%, transparent 50%, rgba(20,22,26,0.32) 100%),
    var(--grey-deep);
  padding: 32px 12px 40px;
  position: relative;
}
.news-bg::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background-image: ${NOISE};
  opacity: 0.45;
  mix-blend-mode: multiply;
  z-index: 3;
}
.news-bg > * { position: relative; z-index: 4; }

.page-actions {
  display: flex;
  justify-content: center;
  gap: 12px;
  margin: 24px auto 0;
}
.back-btn,
.print-btn {
  display: block;
  font-family: 'Noto Sans KR', sans-serif;
  font-size: 13px;
  letter-spacing: 1px;
  background: var(--ink);
  color: var(--cream);
  border: none;
  padding: 10px 22px;
  cursor: pointer;
  z-index: 10;
}
.back-btn:hover, .print-btn:hover { background: #322c22; }
.print-btn { background: var(--red-box); }
.print-btn:hover { background: var(--red-deep); }

.paper-sheet {
  position: relative;
  max-width: 100%;
  margin: 0 auto;
  background:
    radial-gradient(700px 350px at 25% 0%, rgba(255,255,255,0.4), transparent 60%),
    linear-gradient(190deg, #eef1f3 0%, var(--cream) 45%, var(--grey-mid) 100%);
  box-shadow:
    0 14px 44px rgba(20,20,22,0.4),
    0 2px 8px rgba(0,0,0,0.25);
  padding: 34px 38px 40px;
  color: var(--ink);
  font-family: 'Nanum Myeongjo', serif;
  overflow: hidden;
}
/* 종이 섬유질 노이즈 (질감 강화) */
.paper-sheet::before {
  content: "";
  position: absolute;
  inset: 0;
  background-image: ${NOISE};
  background-size: 220px 220px;
  opacity: 0.6;
  mix-blend-mode: multiply;
  pointer-events: none;
}
.paper-sheet > * { position: relative; }

.mast-topline {
  display: flex;
  justify-content: space-between;
  font-family: 'Noto Sans KR', sans-serif;
  font-size: 11px;
  letter-spacing: 2px;
  border-bottom: 1px solid var(--rule);
  padding-bottom: 6px;
  margin-bottom: 10px;
}
.mast-title {
  font-family: 'Playfair Display', serif;
  font-weight: 900;
  font-size: clamp(40px, 7vw, 68px);
  text-align: center;
  letter-spacing: -1px;
  line-height: 1;
  color: #211c14;
}
.mast-rule {
  border-top: 3px solid var(--rule);
  border-bottom: 1px solid var(--rule);
  height: 6px;
  margin: 12px 0 8px;
}
.mast-rule.thin { border-top-width: 1px; height: 4px; margin: 8px 0 0; }
.mast-sub {
  text-align: center;
  font-family: 'Noto Sans KR', sans-serif;
  font-size: 12px;
  letter-spacing: 8px;
}

.mast-title { cursor: pointer; transition: opacity 0.15s; }
.mast-title:hover { opacity: 0.65; }
.mast-title-input {
  display: block;
  width: 100%;
  font-family: 'Playfair Display', serif;
  font-weight: 900;
  font-size: clamp(32px, 6vw, 60px);
  text-align: center;
  letter-spacing: -1px;
  line-height: 1;
  color: #211c14;
  border: none;
  border-bottom: 2px dashed var(--rule);
  background: transparent;
  outline: none;
  padding-bottom: 4px;
}

/* ═══ 오늘의 한 줄 (헤드라인 코멘트 + 무드 태그) ═══ */
.today-comment {
  margin-top: 18px;
  padding: 4px 6px 20px;
  text-align: center;
  border-bottom: 1px solid var(--rule);
}
.today-comment-text {
  font-family: 'Nanum Myeongjo', serif;
  font-style: italic;
  font-size: 14.5px;
  line-height: 1.9;
  word-break: keep-all;
}
.tag-row {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
}
.tag-pill {
  font-family: 'Noto Sans KR', sans-serif;
  font-size: 11.5px;
  letter-spacing: 0.5px;
  color: var(--red-box);
  border: 1px solid var(--red-box);
  border-radius: 999px;
  padding: 3px 10px;
}

.source-link {
  display: inline-block;
  margin-top: 10px;
  font-family: 'Noto Sans KR', sans-serif;
  font-size: 11.5px;
  letter-spacing: 1px;
  color: var(--ink);
  text-decoration: underline;
  text-underline-offset: 3px;
}
.source-link:hover { color: var(--red-box); }

.playlist-list {
  margin-top: 10px;
  list-style: none;
  padding: 0;
  font-family: 'Noto Sans KR', sans-serif;
  font-size: 12px;
}
.playlist-list li {
  padding: 4px 0;
  border-bottom: 1px dotted var(--rule);
}

/* ═══ 오늘의 일정: 목록 + 빈 타임테이블 ═══ */
.schedule-list {
  list-style: none;
  padding: 0;
  font-family: 'Noto Sans KR', sans-serif;
  font-size: 13px;
  line-height: 1.9;
}
.schedule-list li {
  padding-left: 16px;
  position: relative;
  min-height: 1.9em;
  border-bottom: 1px dotted var(--rule);
}
.schedule-list li::before {
  content: "•";
  position: absolute;
  left: 0;
  color: var(--red-box);
}

.timetable-box {
  margin-top: 14px;
  border: 1px solid var(--rule);
  overflow: hidden;
}

/* ═══ 하루다짐: 구분선만 있는 여백 ═══ */
.pledge-divider {
  margin-top: 2px;
  border-top: 1px solid var(--rule);
  /* 옆 칼럼 높이에 여유가 없으면 메이슨리 stretch가 거의 안 먹혀서 손글씨 쓸
     공간이 사실상 사라짐 — 최소 높이를 직접 보장해 항상 빈칸이 보이게 함.
     (stretch로 더 늘어날 여유가 있으면 flex:1인 부모 박스를 따라 더 커짐) */
  min-height: 200px;
}
.timetable {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
}
.timetable td {
  border: 1px solid var(--rule);
}
.tt-period {
  width: 15%;
  text-align: center;
  vertical-align: middle;
  font-family: 'Noto Sans KR', sans-serif;
  font-size: 11px;
  font-weight: 700;
  background: var(--grey-mid);
}
.tt-hour {
  width: 15%;
  font-family: 'Noto Sans KR', sans-serif;
  font-size: 10.5px;
  text-align: left;
  padding: 0 6px;
  white-space: nowrap;
}
.tt-cell {
  width: 70%;
  height: 17px;
  font-family: 'Noto Sans KR', sans-serif;
  font-size: 10.5px;
  text-align: left;
  padding: 0 6px;
}

.back-page { margin-top: 8px; }

/* 균형 2단 메이슨리 — MasonryTwoCol 컴포넌트가 실제 높이를 재서
   더 짧은 열에 박스를 넣는 방식. 내용 길이가 매번 달라져도 자동으로 균형 맞음. */
.masonry-wrap { position: relative; margin-top: 24px; }
.masonry-measure {
  position: absolute;
  top: 0;
  left: 0;
  visibility: hidden;
  pointer-events: none;
  z-index: -1;
}
.masonry-2col {
  display: flex;
  align-items: stretch;
}
.masonry-col {
  flex: 1 1 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.masonry-item + .masonry-item { margin-top: 0; }
/* 짧은 열의 마지막 박스는 테두리를 유지한 채 남는 높이만큼 자연스럽게 늘어나서,
   테두리 없는 빈 여백이 그대로 드러나지 않게 함 */
.masonry-item:last-child { flex: 1; display: flex; }
.masonry-item:last-child > .box {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.box { border: 1.5px solid var(--rule); padding: 14px 14px 16px; margin-bottom: 18px; }
.box-headline { border-width: 2px; }

.label {
  font-family: 'Playfair Display', serif;
  font-style: italic;
  font-weight: 600;
  font-size: 15px;
  text-align: center;
  margin-bottom: 10px;
}
.label.underline { text-decoration: underline; text-underline-offset: 4px; }

.big-number {
  font-family: 'Playfair Display', serif;
  font-weight: 900;
  font-size: 72px;
  text-align: center;
  line-height: 1;
  margin: 4px 0 10px;
}

.headline {
  font-family: 'Nanum Myeongjo', serif;
  font-weight: 800;
  font-size: 24px;
  text-align: center;
  margin-bottom: 12px;
}

.col-text {
  font-size: 13px;
  line-height: 1.8;
  text-align: justify;
  word-break: keep-all;
}
.col-text.small { font-size: 12px; margin-top: 10px; }
.col-text + .col-text { margin-top: 8px; }

.news-photo { margin-bottom: 12px; }
.photo-area {
  width: 100%;
  aspect-ratio: 4 / 3; /* 4:5(세로형)에서 낮춤 — 박스 높이를 줄여 다른 박스와 배치가 빡빡해지지 않게 */
  filter: sepia(0.4) contrast(0.92) brightness(0.98);
}
.photo-image {
  display: block;
  object-fit: cover;
  background: #ddd5c5;
}

.ranked-list {
  list-style: none;
  counter-reset: rank;
  font-family: 'Noto Sans KR', sans-serif;
  padding: 0;
}
.ranked-list li {
  counter-increment: rank;
  font-size: 13px;
  letter-spacing: 0.5px;
  text-align: left;
  padding: 7px 0;
  border-bottom: 1px dotted var(--rule);
}
.ranked-list li::before {
  content: counter(rank) ". ";
  font-family: 'Playfair Display', serif;
  font-weight: 700;
}

.news-footer {
  display: flex;
  align-items: center;
  gap: 26px;
  margin-top: 8px;
  border-top: 3px double var(--rule);
  padding-top: 22px;
}
.vinyl {
  flex-shrink: 0;
  width: 150px;
  aspect-ratio: 1;
  border-radius: 50%;
  background:
    radial-gradient(circle at 35% 30%, rgba(255,255,255,0.12), transparent 45%),
    repeating-radial-gradient(circle, #0e0e0e 0 1.5px, #1c1c1c 1.5px 4px);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 8px 18px rgba(0,0,0,0.4);
}
.vinyl-label {
  width: 44%;
  aspect-ratio: 1;
  border-radius: 50%;
  background: radial-gradient(circle at 40% 35%, #d5c295, #a98f58);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  font-family: 'Playfair Display', serif;
  color: #2a1f0e;
}
.vinyl-label span { font-size: 9px; letter-spacing: 3px; }
.vinyl-label strong { font-size: 22px; font-weight: 900; }
.footer-text { flex: 1; }

@media (max-width: 760px) {
  .masonry-2col { flex-direction: column; }
  .masonry-col + .masonry-col { margin-top: 18px; }
  .paper-sheet { padding: 24px 18px 30px; }
  .news-footer { flex-direction: column; text-align: center; }
  .mail-cabinet { padding: 12px 10px 10px; }
  .photo-drop-controls { flex-direction: column; align-items: stretch; }
  .photo-submit { width: 100%; }
}

/* ═══ 인쇄 (물리 용지 설정만 — 실제 인쇄 내용은 PrintEdition 전용 마크업/CSS를 씀) ═══ */
@media print {
  @page {
    size: A3 landscape;
    margin: 0;
  }
  html, body { margin: 0 !important; background: #fff !important; }
  .page-actions { display: none !important; }
  /* print-sheet이 물리 용지(420x297mm)와 정확히 같은 크기라서,
     감싸는 wrap의 padding/배경이 남아있으면 페이지당 인쇄 가능 영역을 넘겨서
     내용 일부가 다음 장으로 밀려버림(그 밀려난 조각들이 "빈칸 많은 페이지"로 보였던 원인). */
  .print-edition-wrap {
    min-height: 0 !important;
    padding: 0 !important;
    background: #fff !important;
    display: block !important;
  }
  .print-sheet { box-shadow: none !important; }
}

/* ═════════════════════════════════════════════
   1.5 인쇄 전용 레이아웃(PrintEdition) 전용 CSS
   — 화면 신문 레이아웃(.box, 메이슨리 등)과 완전히 분리된, A3 가로 한 장을
     반으로 나눈 고정 mm 크기 스타일. 절취선 기준으로 자르면 A4 낱장 두 장이 됨.
     화면 미리보기에서도 실제 인쇄 크기 그대로 보이도록 항상 켜둠(별도 @media print 불필요).
═════════════════════════════════════════════ */
/* 브라우저는 기본적으로 인쇄 시 배경색/그라디언트를 생략한다(인쇄 대화상자의
   "배경 그래픽" 옵션이 꺼져 있으면). 레코드판 그라디언트, 사진 placeholder
   그라디언트 등이 통째로 안 보이는 문제를 막기 위해 강제로 켜둔다. */
.print-edition-wrap, .print-edition-wrap * {
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
  color-adjust: exact;
}
.print-edition-wrap {
  min-height: 100vh;
  background: #78787c;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  overflow: auto;
}
.print-sheet {
  width: 420mm;
  height: 297mm;
  flex-shrink: 0;
  background: #fff;
  display: flex;
  box-shadow: 0 8px 30px rgba(0,0,0,0.35);
  font-family: 'Nanum Myeongjo', serif;
  color: #1a1a1a;
}
.print-page {
  width: 50%;
  height: 100%;
  box-sizing: border-box;
  padding: 10mm;
  display: flex;
  flex-direction: column;
  gap: 4mm;
  overflow: hidden;
}
.print-page-left {
  border-right: 1px dashed #999;
}

.print-masthead { text-align: center; }
.print-mast-topline {
  display: flex;
  justify-content: space-between;
  font-family: 'Noto Sans KR', sans-serif;
  font-size: 9px;
  letter-spacing: 1px;
  color: #555;
  border-bottom: 1px solid #999;
  padding-bottom: 1.5mm;
  margin-bottom: 2mm;
}
.print-mast-title {
  font-family: 'Playfair Display', serif;
  font-weight: 900;
  font-size: 26px;
  letter-spacing: -0.5px;
  line-height: 1;
  margin: 0;
}
/* 화면판 마스트헤드(.mast-rule/.mast-sub)와 동일한 이중 룰선 + 자간 넓은 부제 구조를
   그대로 축소 적용 — 인쇄판만 따로 압축된 한 줄짜리 디자인을 쓰지 않도록 통일. */
.print-mast-rule {
  border-top: 2px solid #333;
  border-bottom: 1px solid #333;
  height: 3px;
  margin: 2mm 0 1.5mm;
}
.print-mast-rule.thin { border-top-width: 1px; height: 2px; margin: 1.5mm 0 0; }
.print-mast-sub {
  text-align: center;
  font-family: 'Noto Sans KR', sans-serif;
  font-size: 8px;
  letter-spacing: 4px;
  margin: 0;
}

.print-today-comment {
  margin-top: 2mm;
  padding: 1mm 2mm 3mm;
  text-align: center;
  border-bottom: 1px solid #999;
}
.print-today-comment-text {
  font-family: 'Nanum Myeongjo', serif;
  font-style: italic;
  font-size: 10.5px;
  line-height: 1.6;
  word-break: keep-all;
  margin: 0;
}
.print-tag-row {
  margin-top: 2mm;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 1.5mm;
}
.print-tag-pill {
  font-family: 'Noto Sans KR', sans-serif;
  font-size: 8px;
  letter-spacing: 0.3px;
  color: #a33;
  border: 1px solid #a33;
  border-radius: 999px;
  padding: 0.8mm 2.2mm;
}

.print-box {
  border: 1px solid #999;
  box-sizing: border-box;
  padding: 3mm 4mm;
  overflow: hidden;
}
.print-label {
  font-family: 'Playfair Display', serif;
  font-style: italic;
  font-weight: 600;
  font-size: 13px;
  text-align: center;
  margin: 0 0 2mm;
}
.print-box-text {
  font-family: 'Noto Sans KR', sans-serif;
  font-size: 11px;
  line-height: 1.55;
  margin: 0;
}
.print-headline-title {
  font-family: 'Playfair Display', serif;
  font-weight: 700;
  font-size: 16px;
  line-height: 1.3;
  margin: 0 0 2mm;
}

/* 페이지 안쪽 큰 그리드: [왼쪽 큰 박스] + [오른쪽 위/아래 박스 두 개]
   높이는 mm로 손으로 맞추지 않고 flex로 남는 공간을 자동 배분 —
   페이지 자체가 297mm로 고정돼 있어서 flex 체인을 타고 절대 넘치지 않음. */
.print-row-main {
  display: flex;
  flex: 2;
  gap: 4mm;
  min-height: 0; /* flex 자식이 내용 때문에 부모를 밀어내지 않도록 */
}
/* 왼쪽 칼럼(메인 기사 + 4번째 기사)과 오른쪽 칼럼(사이드 기사 2개)을
   같은 구조로 맞춤 — 둘 다 내용만큼만 높이를 차지하는 박스 스택. */
.print-col-main {
  flex: 0 0 47%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4mm;
  min-height: 0;
}
.print-col-main > .print-box {
  flex: 0 0 auto;
  max-height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.print-col-sub {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4mm;
  min-height: 0;
}
/* 기본값: 글 박스는 내용만큼만 높이를 차지(늘리지 않음). */
.print-col-sub > .print-box {
  flex: 0 0 auto;
  max-height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.print-page-footer-date {
  flex: 0 0 auto;
  margin: 0;
  padding-top: 1.5mm;
  border-top: 1px solid #ccc;
  text-align: center;
  font-family: 'Noto Sans KR', sans-serif;
  font-size: 9.5px;
  letter-spacing: 1px;
  color: #666;
}

/* 2페이지: 오늘의 일정 / 사진 / 오늘 다짐 / 어제의 플레이리스트 — 동일 크기 2x2 칸.
   여백(일정표 빈칸, 다짐 박스 등)은 손글씨용으로 의도된 디자인. */
.print-grid-2x2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  grid-template-rows: 1fr 1fr;
  gap: 4mm;
  flex: 1;
  min-height: 0;
}
.print-grid-2x2 > .print-box {
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
}

.print-pledge-divider {
  margin-top: 2mm;
  border-top: 1px solid #999;
  flex: 1;
}

.print-playlist-body {
  display: flex;
  align-items: center;
  gap: 3mm;
  flex: 1;
  min-height: 0;
}
.print-vinyl {
  width: 26mm;
  aspect-ratio: 1;
  flex-shrink: 0;
  border-radius: 50%;
  background:
    radial-gradient(circle at 35% 30%, rgba(255,255,255,0.12), transparent 45%),
    repeating-radial-gradient(circle, #0e0e0e 0 0.6mm, #1c1c1c 0.6mm 1.6mm);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2mm 4mm rgba(0,0,0,0.35);
}
.print-vinyl-label {
  width: 44%;
  aspect-ratio: 1;
  border-radius: 50%;
  background: radial-gradient(circle at 40% 35%, #d5c295, #a98f58);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  font-family: 'Playfair Display', serif;
  color: #2a1f0e;
}
.print-vinyl-label span { font-size: 5.5px; letter-spacing: 1px; }
.print-vinyl-label strong { font-size: 11px; font-weight: 900; }
.print-playlist-text {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.print-photo-img {
  width: 100%;
  flex: 1;
  min-height: 0;
  object-fit: cover;
  display: block;
}
.print-schedule-list {
  list-style: none;
  margin: 0 0 2mm;
  padding: 0;
  font-family: 'Noto Sans KR', sans-serif;
  font-size: 10.5px;
  line-height: 1.5;
  flex-shrink: 0; /* 아래 타임테이블에 밀려서 눌려 안 보이는 일이 없도록 고정 */
}
.print-schedule-list li {
  min-height: 4.2mm;
  padding-left: 3mm;
  position: relative;
  border-bottom: 1px dotted #999;
}
.print-schedule-list li::before {
  content: "•";
  position: absolute;
  left: 0;
  color: #a33;
}

.print-timetable {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  font-family: 'Noto Sans KR', sans-serif;
}
.print-timetable td {
  border: 1px solid #ccc;
  height: 4.1mm;
}
.print-tt-period {
  width: 14%;
  text-align: center;
  vertical-align: middle;
  font-size: 9px;
}
.print-tt-hour {
  width: 20%;
  font-size: 8.5px;
  padding-left: 2mm;
}
.print-tt-cell {
  font-size: 8px;
  padding-left: 1.5mm;
}

.print-playlist-list {
  list-style: none;
  margin: 2mm 0 0;
  padding: 0;
  font-family: 'Noto Sans KR', sans-serif;
  font-size: 10.5px;
  line-height: 1.6;
}
`;
