import React, { useState } from "react";
import ReactDOM from "react-dom/client";
import { MailboxCalendar, NewspaperPage, css } from "../src/App_realistic.jsx";

/* ═════════════════════════════════════════════
   로그인 없이 바로 우편함부터 시작하는 테스트 진입점.
   MailboxCalendar / NewspaperPage는 src/App_realistic.jsx의 실제 컴포넌트를
   그대로 가져다 쓰기 때문에, 레이아웃/기능을 여기서 고칠 필요 없이
   src/App_realistic.jsx만 수정하면 이 테스트 화면에도 그대로 반영됩니다.
   (나중에 따로 복사해서 덮어씌울 필요 없음 — 같은 파일을 공유함)

   실행: FE 폴더에서 npm run dev 실행 후
        http://localhost:5173/test/ 접속
═════════════════════════════════════════════ */

function TestApp() {
  const [selectedDate, setSelectedDate] = useState(null);

  return (
    <>
      <style>{css}</style>
      {selectedDate === null ? (
        <MailboxCalendar onSelectDate={setSelectedDate} />
      ) : (
        <NewspaperPage date={selectedDate} onBack={() => setSelectedDate(null)} />
      )}
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<TestApp />);
