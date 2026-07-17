<script lang="ts">
	import TrashIcon from '@lucide/svelte/icons/trash';
	import CrossIcon from '@lucide/svelte/icons/x';
	import { Button, buttonVariants } from '$lib/components/ui/button';
	import * as Dialog from '$lib/components/ui/dialog/index.js';
	import { toast } from 'svelte-sonner';

    interface Props {
        deleteIds: number[];
        deleteHook: (id: number) => Promise<boolean>;
        onDeleted: () => Promise<void> | void;
    }

	let {
		deleteIds = $bindable(),
        deleteHook,
		onDeleted
	}: Props = $props();

	async function deleteSelected() {
		let successCount = 0;
		let errorCount = 0;
		// FIXME: waitgroup instead of awaiting each request
		for (const id of deleteIds) {
			console.log(`delete template id ${id}`);
			let s = await deleteHook(id);
			if (s) {
				successCount++;
			} else {
				errorCount++;
			}
		}
		toast.success(`Deleted ${successCount} templates, errors: ${errorCount}`);
		deleteIds = [];
		await onDeleted();
	}
</script>

{#if deleteIds.length > 0}
	<div
		class="fixed top-4 left-1/2 -translate-x-1/2 rounded-md p-2 bg-background flex items-center gap-5 justify-between border-1 border-border"
	>
		<p>Selected {deleteIds.length} templates</p>
		<Dialog.Root>
			<Dialog.Trigger>
				<Button variant="destructive"><TrashIcon /></Button>
			</Dialog.Trigger>
			<Dialog.Content>
				<Dialog.Header>
					<Dialog.Title>Are you sure?</Dialog.Title>
					<Dialog.Description>This action cannot be undone.</Dialog.Description>
				</Dialog.Header>
				<Dialog.Footer>
					<Dialog.Close type="button" class={buttonVariants({ variant: 'outline' })}>
						Cancel
					</Dialog.Close>
					<Button
						type="button"
						class={buttonVariants({ variant: 'destructive' })}
						onclick={deleteSelected}>Delete</Button
					>
				</Dialog.Footer>
			</Dialog.Content>
		</Dialog.Root>
		<Button variant="outline" onclick={() => (deleteIds = [])}><CrossIcon /></Button>
	</div>
{/if}
