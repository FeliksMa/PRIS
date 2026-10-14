import Script from "next/script";
import { requireChatGPTUser } from "./chatgpt-auth";
export const dynamic = "force-dynamic";
export default async function Home() {
  await requireChatGPTUser("/");
  return <>
    <link rel="stylesheet" href="/desk.css" />
    <aside className="sidebar">
      <a className="brand" href="#home"><span className="logo">P<span>·</span></span><span>PRIS<small>RESEARCH DESK</small></span></a>
      <div className="nav-label">你的研究空间</div>
      <nav><button data-view="home" className="active">◈ <span>研究概览</span></button><button data-view="reports">▤ <span>每日新知</span></button><button data-view="papers">▧ <span>论文与研究</span></button><button data-view="preferences">☷ <span>兴趣与偏好</span></button><button data-view="chat">✳ <span>和 PRIS 说话</span></button><button data-view="activity">◷ <span>反馈与记录</span></button></nav>
      <div className="sidebar-foot"><span className="dot" /> 私人云端研究空间<small>让新知有迹可循。</small><a href="/signout-with-chatgpt?return_to=/" target="_top">退出登录</a></div>
    </aside>
    <main><header className="topbar"><span id="breadcrumb">工作台 / 研究概览</span><span className="local-badge">● PRIVATE CLOUD</span></header><div id="page" aria-live="polite"><div className="empty">正在连接你的研究空间…</div></div></main>
    <dialog id="detail"><div className="dialog-top"><span>论文阅读室</span><button id="close-detail" aria-label="关闭">×</button></div><div id="detail-content" /></dialog>
    <div id="toast" role="status" />
    <Script src="/desk.js" strategy="afterInteractive" />
  </>;
}
