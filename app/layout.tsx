import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "HWP 영어시험 문항 분석기",
  description: "HWP 기출문제를 자동 분석하여 엑셀로 다운로드",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <body className="antialiased min-h-screen">
        {children}
      </body>
    </html>
  );
}
