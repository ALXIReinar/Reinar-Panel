<script lang="ts">
	import PlusIcon from '@lucide/svelte/icons/plus';
	import CheckIcon from '@lucide/svelte/icons/check';
	import ChevronsUpDownIcon from '@lucide/svelte/icons/chevrons-up-down';
	import { Button, buttonVariants } from '$lib/components/ui/button';
	import * as Dialog from '$lib/components/ui/dialog/index.js';
	import * as Popover from '$lib/components/ui/popover';
	import * as Command from '$lib/components/ui/command';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';
	import { Textarea } from '$lib/components/ui/textarea';
	import { toast } from 'svelte-sonner';
	import { tick } from 'svelte';
	import { cn } from '$lib/utils';
	import { CreateTemplate, PostTemplateForm } from '$lib/api/templates';

	let { onCreated }: { onCreated: () => Promise<void> | void } = $props();

	let open = $state(false);
	let title = $state("");
	async function createTemplate() {
		let form = new PostTemplateForm(title);
		let s = await CreateTemplate(form);
		if (s) {
			toast.success(`Created a new template`);
			await onCreated();
		} else {
			toast.error(`Failed to create a new template`);
		}

        // cleanup
		open = false;
        title = "";
	}

	const statusList = [
		{ value: '1', label: 'System' },
		{ value: '2', label: 'User' }
	];

	let popoverOpen = $state(false);
	let value = $state('');
	let triggerRef = $state<HTMLButtonElement>(null!);

	const selectedValue = $derived(statusList.find((f) => f.value === value)?.label);

	// We want to refocus the trigger button when the user selects
	// an item from the list so users can continue navigating the
	// rest of the form with the keyboard.
	function closeAndFocusTrigger() {
		popoverOpen = false;
		tick().then(() => {
			triggerRef.focus();
		});
	}
</script>

<Dialog.Root bind:open>
	<form>
		<Dialog.Trigger>
			<Button size="lg"><PlusIcon /> Create template</Button>
		</Dialog.Trigger>
		<Dialog.Content>
			<Dialog.Header>
				<Dialog.Title>Create template</Dialog.Title>
			</Dialog.Header>
			<div class="grid gap-4">
				<div class="grid gap-3">
					<Label for="title-in">Title</Label>
					<Input bind:value={title} id="title-in" name="title" />
				</div>
				<!-- <div class="grid gap-3"> -->
				<!-- 	<Label for="url_tmp-in">URL template</Label> -->
				<!-- 	<Textarea id="url_tmp-in" name="url_tmp" /> -->
				<!-- </div> -->
				<!-- <div class="grid gap-3"> -->
				<!-- 	<Label for="url_tmp-in">Status</Label> -->
				<!-- 	<Popover.Root bind:open={popoverOpen}> -->
				<!-- 		<Popover.Trigger bind:ref={triggerRef}> -->
				<!-- 			{#snippet child({ props })} -->
				<!-- 				<Button -->
				<!-- 					variant="outline" -->
				<!-- 					class="w-[200px] justify-between" -->
				<!-- 					{...props} -->
				<!-- 					role="combobox" -->
				<!-- 					aria-expanded={popoverOpen} -->
				<!-- 				> -->
				<!-- 					{selectedValue || 'Select a status...'} -->
				<!-- 					<ChevronsUpDownIcon class="ms-2 size-4 shrink-0 opacity-50" /> -->
				<!-- 				</Button> -->
				<!-- 			{/snippet} -->
				<!-- 		</Popover.Trigger> -->
				<!-- 		<Popover.Content class="w-[200px] p-0"> -->
				<!-- 			<Command.Root> -->
				<!-- 				<Command.Group> -->
				<!-- 					{#each statusList as status} -->
				<!-- 						<Command.Item -->
				<!-- 							value={status.value} -->
				<!-- 							onSelect={() => { -->
				<!-- 								value = status.value; -->
				<!-- 								closeAndFocusTrigger(); -->
				<!-- 							}} -->
				<!-- 						> -->
				<!-- 							<CheckIcon -->
				<!-- 								class={cn('me-2 size-4', value !== status.value && 'text-transparent')} -->
				<!-- 							/> -->
				<!-- 							{status.label} -->
				<!-- 						</Command.Item> -->
				<!-- 					{/each} -->
				<!-- 				</Command.Group> -->
				<!-- 			</Command.Root> -->
				<!-- 		</Popover.Content> -->
				<!-- 	</Popover.Root> -->
				<!-- </div> -->
			</div>
			<Dialog.Footer>
				<Dialog.Close type="button" class={buttonVariants({ variant: 'outline' })}>
					Cancel
				</Dialog.Close>
				<Button type="button" onclick={createTemplate}>Save</Button>
			</Dialog.Footer>
		</Dialog.Content>
	</form>
</Dialog.Root>
