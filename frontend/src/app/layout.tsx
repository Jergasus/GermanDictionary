import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin", "latin-ext"],
  variable: "--font-inter",
});

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  viewportFit: "cover",
};

export const metadata: Metadata = {
  title: "Wörterbuch — Diccionario Alemán Español",
  description:
    "Diccionario alemán-español rápido, limpio y sin anuncios. Busca palabras en alemán o español con traducción, ejemplos y pronunciación.",
  keywords: [
    "diccionario alemán español",
    "wörterbuch deutsch spanisch",
    "german spanish dictionary",
    "traducción alemán español",
  ],
  openGraph: {
    title: "Wörterbuch — Diccionario Alemán Español",
    description: "Diccionario alemán-español rápido, limpio y sin anuncios.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="es">
      <body className={`${inter.variable} font-sans antialiased`}>
        {children}
      </body>
    </html>
  );
}
