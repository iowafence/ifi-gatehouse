import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = {title:'IFI Gatehouse | Bid Control',description:'Commercial fence estimating with human gates'};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="en"><body>{children}</body></html>}
