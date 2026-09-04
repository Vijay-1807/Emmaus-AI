"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function HistoryAliasPage() {
  const router = useRouter();
  useEffect(() => { router.replace("/investigations"); }, [router]);
  return null;
}
