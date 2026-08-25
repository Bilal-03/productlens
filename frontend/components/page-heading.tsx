export function PageHeading({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: React.ReactNode }) {
  return <div className="mb-7 flex flex-col justify-between gap-4 md:flex-row md:items-end"><div><div className="eyebrow mb-2">{eyebrow}</div><h1 className="text-2xl font-bold tracking-[-.025em] md:text-3xl">{title}</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-[#697080]">{description}</p></div>{action}</div>;
}

