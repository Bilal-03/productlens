import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { AppShell } from "@/components/app-shell";

export const metadata: Metadata = { title: "ProductLens AI", description: "Evidence-first product analytics copilot" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body><Providers><AppShell>{children}</AppShell></Providers></body></html>;
}

