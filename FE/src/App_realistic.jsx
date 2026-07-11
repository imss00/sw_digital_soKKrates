import React, { useState, useEffect, useRef, useLayoutEffect } from "react";
import { fetchJournal } from "./api/journal";
import { PHOTO_LIMITS, uploadPhotos } from "./api/photos";
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
const TIMETABLE_BLANK_COLS = 6;

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
   2. 날짜별 페이지 — 신문 컨셉
═════════════════════════════════════════════ */

function NewspaperPage({ date, onBack }) {
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

  useEffect(() => {
    let cancelled = false;
    setJournal(null);
    setJournalError(null);

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
      });

    return () => {
      cancelled = true;
    };
  }, [targetDate]);

  // journal 필드 → 신문 레이아웃 매핑
  const mainArticle = journal?.article_intros?.find((a) => a.is_main) ?? null;
  const sideArticles = journal?.article_intros?.filter((a) => !a.is_main) ?? [];
  const sideArticleLeft = sideArticles[0] ?? null;
  const sideArticleRight = sideArticles[1] ?? null;
  const reflectionTags = journal?.reflection
    ? journal.reflection
        .split("/")
        .map((t) => t.trim())
        .filter(Boolean)
    : [];

  // schedule는 텍스트 한 덩어리로 옴 — 줄바꿈/쉼표/가운뎃점 기준으로 나눠서 목록화.
  // "일정 없음"이거나 내용이 없으면 빈 칸 3개만 보여줌.
  const scheduleText = journal?.schedule?.trim() ?? "";
  const scheduleItems =
    scheduleText && scheduleText !== "일정 없음"
      ? scheduleText
          .split(/\n|,|·/)
          .map((s) => s.trim())
          .filter(Boolean)
      : [];
  const scheduleRows = scheduleItems.length > 0 ? scheduleItems : ["", "", ""];

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

  return (
    <div className="news-bg">
      <div className="paper-sheet">
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
          resetKey={`${targetDate}-top-${journal ? "loaded" : "loading"}`}
          items={[
            {
              key: "headline",
              node: (
                <section className="box box-headline">
                  <h2 className="headline">
                    {mainArticle ? mainArticle.title : "Headline of the Day"}
                  </h2>
                  <figure className="news-photo">
                    <div
                      className="photo-area"
                      style={{
                        background: `linear-gradient(150deg,
                          hsl(${(day * 37) % 360}, 18%, 62%),
                          hsl(${(day * 37 + 30) % 360}, 22%, 38%))`,
                      }}
                    />
                    <figcaption>
                      {journal?.photo_narrative ||
                        "오늘의 대표 사진이 들어갈 자리. 캡션은 두 줄 이내로 짧게 씁니다."}
                    </figcaption>
                  </figure>
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
                              {Array.from({ length: TIMETABLE_BLANK_COLS }).map((_, i) => (
                                <td className="tt-cell" key={i} />
                              ))}
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
                  <p className="date-stamp">{month + 1}월 {day}일 오전</p>
                </section>
              ),
            },
          ]}
        />

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
                  <p className="date-stamp">{dateLabel}</p>
                </section>
              ),
            },
            {
              key: "pledge",
              node: (
                <section className="box">
                  <h3 className="label">하루다짐</h3>
                  <div className="pledge-box" />
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

      <button className="back-btn" onClick={onBack}>← 우편함으로</button>
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

export default function App() {
  const [selectedDate, setSelectedDate] = useState(null);
  const [loggedIn, setLoggedIn] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);
  const authUser = getAuthUser();

  useEffect(() => {
    initAuthFromUrl(); // 백엔드가 ?token=... 을 붙여 리다이렉트해오면 여기서 저장됨
    setLoggedIn(isLoggedIn());
    setAuthChecked(true);
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
        <NewspaperPage date={selectedDate} onBack={() => setSelectedDate(null)} />
      )}
    </>
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

.back-btn {
  display: block;
  margin: 24px auto 0;
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
.back-btn:hover { background: #322c22; }

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

/* ═══ 하루다짐: 손으로 적는 빈 줄노트 박스 ═══ */
.pledge-box {
  margin-top: 4px;
  min-height: 110px;
  border: 1px solid var(--rule);
  background: repeating-linear-gradient(
    to bottom,
    transparent 0,
    transparent 25px,
    var(--rule) 25px,
    var(--rule) 26px
  );
  opacity: 0.85;
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
  width: 13%;
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
  height: 17px;
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

.date-stamp {
  font-family: 'Playfair Display', serif;
  font-weight: 700;
  font-size: 17px;
  text-align: right;
  margin-top: 12px;
  border-top: 1px solid var(--rule);
  padding-top: 8px;
}

.news-photo { margin-bottom: 12px; }
.photo-area {
  width: 100%;
  aspect-ratio: 4 / 5;
  filter: sepia(0.4) contrast(0.92) brightness(0.98);
}
.news-photo figcaption {
  font-size: 11.5px;
  line-height: 1.6;
  border: 1px solid var(--rule);
  border-top: none;
  padding: 8px 10px;
  text-align: center;
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

/* ═══ 인쇄용 (A4 양면 — 앞면: 마스트헤드~헤드라인 기사, 뒷면: back-page) ═══ */
@media print {
  @page {
    size: A4;
    margin: 14mm;
  }

  body { background: #fff !important; }

  /* 텍스처/노이즈/비네팅은 잉크만 낭비하고 가독성을 떨어뜨려서 인쇄 시 제거 */
  .news-bg::before,
  .paper-sheet::before,
  .stripe-bg::before,
  .stripe-bg::after {
    display: none !important;
  }

  .back-btn { display: none !important; }

  .news-bg {
    background: none !important;
    padding: 0 !important;
  }
  .paper-sheet {
    max-width: 100%;
    box-shadow: none !important;
    padding: 0 !important;
  }

  /* 박스 하나가 페이지 경계에서 잘리지 않도록 — 텍스트가 끊긴 채 다음 장으로 안 넘어가게 함 */
  .box,
  .today-comment,
  .masthead,
  .news-footer,
  figure.news-photo {
    break-inside: avoid;
    page-break-inside: avoid;
  }

  /* 뒷면 내용(사이드 기사2 + 키워드 Top5 + 플레이리스트)은 항상 다음 장(뒷면)에서 시작 */
  .back-page {
    break-before: page;
    page-break-before: always;
  }

  a.source-link {
    color: var(--ink) !important;
    text-decoration: underline;
  }
}
`;
