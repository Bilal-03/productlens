import Link from "next/link";
import { Button, Card } from "@/components/ui";
export default function NotFound(){return <Card className="grid min-h-[60vh] place-items-center text-center"><div><div className="eyebrow">404</div><h1 className="mt-3 text-2xl font-bold">Analysis page not found</h1><p className="mt-2 text-sm text-[#747b8b]">The requested workspace view does not exist.</p><Button asChild className="mt-5"><Link href="/">Return to overview</Link></Button></div></Card>}

