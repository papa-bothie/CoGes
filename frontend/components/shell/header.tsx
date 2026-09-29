"use client";

import { LogOut, Menu } from "lucide-react";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import type { Me } from "@/lib/api/schema";
import { logout, loginUrl } from "@/lib/auth/session";
import { labels } from "@/lib/labels";
import { pageTitle } from "@/lib/navigation";

import { NotificationBell } from "./notification-bell";
import { SidebarContent } from "./sidebar";
import { ThemeToggle } from "./theme-toggle";

function roleLabel(me: Me): string {
  return me.roles.map((role) => role.description ?? role.name).join(", ");
}

function initial(name: string): string {
  return name.trim().charAt(0).toUpperCase() || "?";
}

export function Header({ me }: { me: Me }) {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const [leaving, setLeaving] = useState(false);

  const handleLogout = async () => {
    setLeaving(true);
    await logout();
    // Rechargement complet : le cache des requêtes et le jeton en mémoire disparaissent.
    window.location.assign(loginUrl("logout"));
  };

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b bg-card px-4 md:px-6">
      <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
        <SheetTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="md:hidden"
            aria-label={labels.nav.openMenu}
          >
            <Menu aria-hidden />
          </Button>
        </SheetTrigger>
        <SheetContent side="left" className="w-64 p-0">
          <SheetTitle className="sr-only">{labels.nav.mainNavigation}</SheetTitle>
          <SidebarContent
            companyName={me.company.name}
            permissions={me.permissions}
            pathname={pathname}
            onNavigate={() => setMenuOpen(false)}
          />
        </SheetContent>
      </Sheet>

      <div className="min-w-0 flex-1">
        <p className="truncate text-lg leading-tight font-semibold">{pageTitle(pathname)}</p>
        <p className="truncate text-xs text-muted-foreground">{me.company.name}</p>
      </div>

      <div className="flex items-center gap-1 md:gap-2">
        <NotificationBell />
        <ThemeToggle />
        <div className="ml-1 hidden items-center gap-2.5 sm:flex">
          <div className="text-right leading-tight">
            <p className="text-sm font-medium">{me.user.full_name}</p>
            <p className="text-xs text-muted-foreground">{roleLabel(me)}</p>
          </div>
          <Avatar className="size-9">
            <AvatarFallback className="bg-primary/10 font-semibold text-primary">
              {initial(me.user.full_name)}
            </AvatarFallback>
          </Avatar>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={handleLogout}
          disabled={leaving}
          aria-label={labels.header.logout}
          title={labels.header.logout}
        >
          <LogOut aria-hidden />
        </Button>
      </div>
    </header>
  );
}
