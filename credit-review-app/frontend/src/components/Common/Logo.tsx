import { Link } from "@tanstack/react-router"

import { cn } from "@/lib/utils"

interface LogoProps {
  variant?: "full" | "icon" | "responsive"
  className?: string
}

export function Logo({ variant = "full", className }: LogoProps) {
  const icon = (
    <div className="flex size-8 items-center justify-center rounded-md bg-primary text-base font-bold text-primary-foreground">
      信
    </div>
  )

  if (variant === "icon") {
    return icon
  }

  return (
    <Link to="/" className="flex items-center gap-2">
      {icon}
      <span
        className={cn(
          "text-base font-semibold",
          variant === "responsive" && "group-data-[collapsible=icon]:hidden",
          className,
        )}
      >
        信贷资料核对
      </span>
    </Link>
  )
}
