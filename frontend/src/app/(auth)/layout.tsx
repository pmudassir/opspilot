export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex flex-1 flex-col items-center justify-center px-4 py-16">
      <div className="w-full max-w-sm">
        <p className="mb-8 text-sm font-semibold tracking-tight text-teal-800">OpsPilot</p>
        {children}
      </div>
    </main>
  );
}
