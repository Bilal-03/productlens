import { notFound } from "next/navigation";
import { AnalyticsModule } from "@/components/analytics-module";
const modules=["funnels","retention","cohorts","segments","feature-adoption"] as const;
export default async function Page({params}:{params:Promise<{module:string}>}){const {module}=await params;if(!modules.includes(module as typeof modules[number]))notFound();return <AnalyticsModule module={module as typeof modules[number]}/>}

