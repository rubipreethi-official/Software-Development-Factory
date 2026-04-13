import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AI Factory — Mission Control",
  description: "Semi-Autonomous Software Development Orchestrator Dashboard",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full bg-hud-bg text-foreground selection:bg-hud-accent/30 selection:text-white">
        {/* Animated HUD Viewport Glows */}
        <div className="hud-bg-glow top-[-20%] left-[-20%]" />
        <div className="hud-bg-glow bottom-[-20%] right-[-20%]" style={{ animationDelay: "-5s" }} />
        
        <main className="relative z-10 flex min-h-screen flex-col">
          {children}
        </main>
      </body>
    </html>
  );
}
