import type { Metadata } from "next";

import "./globals.css";
import "@/components/review/reviewer.css";
import { Providers } from "./providers";
import { AppShell } from "@/components/AppShell";

export const metadata: Metadata = {
  title: "DMEF Reviewer",
  description: "Document Matching Early Finder reviewer workspace",
};

const themeBootScript = `
(function () {
  try {
    var key = "dmef_theme";
    var stored = localStorage.getItem(key);
    var theme =
      stored === "light" || stored === "dark" || stored === "harbor" || stored === "ember"
        ? stored
        : "light";
    document.documentElement.setAttribute("data-theme", theme);
  } catch (e) {
    document.documentElement.setAttribute("data-theme", "light");
  }
})();
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="light" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBootScript }} />
      </head>
      <body>
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
