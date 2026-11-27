import './globals.css';
import type {Metadata} from 'next';

export const metadata: Metadata = {title: 'Rivet AI Studio', description: 'Production control centre'};

// Applies the saved theme before paint (no flash). Only reads localStorage; nothing sensitive is stored there.
const themeScript = "try{var t=localStorage.getItem('odd-theme');if(t)document.documentElement.dataset.theme=t}catch(e){}";

export default function RootLayout({children}: {children: React.ReactNode}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{__html: themeScript}} /></head>
      <body>{children}</body>
    </html>
  );
}
