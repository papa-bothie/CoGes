"use client";

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { useProduct } from "@/lib/api/queries/products";
import { labels } from "@/lib/labels";

import { ProductForm } from "../../product-form";

export function EditProductView({ productId }: { productId: string }) {
  const product = useProduct(productId);
  if (product.isError) {
    return <ErrorState error={product.error} onRetry={() => void product.refetch()} />;
  }
  if (!product.data) return <Skeleton className="h-96 w-full" />;
  return (
    <>
      <PageHeader title={labels.products.editTitle(product.data.name)} />
      <ProductForm product={product.data} />
    </>
  );
}
