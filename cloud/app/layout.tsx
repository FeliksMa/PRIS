import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PRIS · Research Desk",
  description: "你的私人云端研究空间：日报、论文、研究偏好与AI对话。",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body className="antialiased">{children}</body>
    </html>
  );
}
