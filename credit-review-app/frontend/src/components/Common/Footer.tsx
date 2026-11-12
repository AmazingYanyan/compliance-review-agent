export function Footer() {
  const currentYear = new Date().getFullYear()
  return (
    <footer className="border-t px-6 py-4">
      <p className="text-sm text-muted-foreground">信贷资料核对 · {currentYear}</p>
    </footer>
  )
}
