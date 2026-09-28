import { AppShell } from "@/components/app-shell";

export default function OrgLayout({ children }: LayoutProps<"/orgs/[orgId]">) {
  return <AppShell>{children}</AppShell>;
}
