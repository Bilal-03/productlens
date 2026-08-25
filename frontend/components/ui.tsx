import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) { return twMerge(clsx(inputs)); }

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-lg text-sm font-semibold transition-colors disabled:pointer-events-none disabled:opacity-50 focus-visible:outline focus-visible:outline-2",
  { variants: { variant: {
    primary: "bg-[#635bff] text-white hover:bg-[#5149e6]",
    secondary: "border border-[#e1e5ec] bg-white text-[#303542] hover:bg-[#f4f5f8]",
    ghost: "text-[#596071] hover:bg-[#f1f2f6]",
    danger: "bg-[#fff0f1] text-[#b82f42] hover:bg-[#ffe4e7]",
  }, size: { md: "h-10 px-4", sm: "h-8 px-3", lg: "h-12 px-5" } }, defaultVariants: { variant: "primary", size: "md" } }
);

export function Button({ asChild, className, variant, size, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Component = asChild ? Slot : "button";
  return <Component className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("panel", className)} {...props} />;
}

export function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "success" | "warning" | "accent" }) {
  const styles = { neutral: "bg-[#f1f2f5] text-[#596071]", success: "bg-[#e8f7f1] text-[#167452]", warning: "bg-[#fff5e7] text-[#9b6017]", accent: "bg-[#eeecff] text-[#5046d8]" };
  return <span className={cn("inline-flex rounded-full px-2.5 py-1 text-xs font-semibold", styles[tone])}>{children}</span>;
}

