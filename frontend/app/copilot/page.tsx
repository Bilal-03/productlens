import { Suspense } from "react";
import { Copilot } from "@/components/copilot";
export default function Page(){return <Suspense fallback={<div className="skeleton h-80"/>}><Copilot/></Suspense>}

