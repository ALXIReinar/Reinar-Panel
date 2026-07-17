<script lang="ts">
	import PlusIcon from '@lucide/svelte/icons/plus';
	import CheckIcon from '@lucide/svelte/icons/check';
	import ChevronsUpDownIcon from '@lucide/svelte/icons/chevrons-up-down';
	import { Button, buttonVariants } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';
	import * as Dialog from '$lib/components/ui/dialog/index.js';
	import { toast } from 'svelte-sonner';
	import { PostProtocolForm, CreateProtocol } from '$lib/api/protocols';
	import * as Command from '$lib/components/ui/command';
	import * as Popover from '$lib/components/ui/popover';
	import { FetchTemplates, type Template } from '$lib/api/templates';
	import { tick } from 'svelte';
	import { cn } from '$lib/utils';

	interface Props {
		onCreated: () => Promise<void>;
	}

	let { onCreated }: Props = $props();

	let open = $state(false);
	let name = $state('');
	let template: Template | null = $state(null);
	let templates = $state<Template[]>([]);
	let templatesLoading = $state(false);

	let templateSelectorOpen = $state(false);
	let triggerRef = $state<HTMLButtonElement>(null!);
	const selectedValue = $derived(templates.find((f) => f === template)?.title);

	async function loadTemplates() {
		templatesLoading = true;
		try {
			templates = await FetchTemplates(true, 100);
		} finally {
			templatesLoading = false;
		}
	}

	function onTemplateSelectorOpenChange(isOpen: boolean) {
		if (isOpen) loadTemplates();
	}

	function closeAndFocusTrigger() {
		templateSelectorOpen = false;
		tick().then(() => {
			triggerRef.focus();
		});
	}

	async function createProtocol() {
        if (name === '') {
			toast.error(`Enter a name`);
            return
        }
        if (template === null) {
			toast.error(`Select a template`);
            return
        }

		let form = new PostProtocolForm(name, template.id);
		let s = await CreateProtocol(form);

		if (s) {
			toast.success(`Created a new protocol`);
			await onCreated();
		} else {
			toast.error(`Failed to create a new protocol`);
		}

		// cleanup
		open = false;
		name = '';
		template = null;
	}
</script>

<Dialog.Root bind:open>
	<form>
		<Dialog.Trigger>
			<Button size="lg"><PlusIcon /> Create protocol</Button>
		</Dialog.Trigger>
		<Dialog.Content>
			<Dialog.Header>
				<Dialog.Title>Create protocol</Dialog.Title>
			</Dialog.Header>
			<div class="grid gap-4">
				<div class="grid gap-3">
					<Label for="name-in">Name</Label>
					<Input bind:value={name} id="name-in" name="name" />
				</div>
				<div class="grid gap-3">
					<Label>Template</Label>
					<Popover.Root bind:open={templateSelectorOpen} onOpenChange={onTemplateSelectorOpenChange}>
						<Popover.Trigger bind:ref={triggerRef}>
							{#snippet child({ props })}
								<Button
									variant="outline"
									class="w-[200px] justify-between"
									{...props}
									role="combobox"
									aria-expanded={templateSelectorOpen}
								>
									{selectedValue || 'Select a template...'}
									<ChevronsUpDownIcon class="ms-2 size-4 shrink-0 opacity-50" />
								</Button>
							{/snippet}
						</Popover.Trigger>
						<Popover.Content class="w-[200px] p-0">
							<Command.Root>
								<Command.Input placeholder="Search template..." />
								<Command.List>
									{#if templatesLoading}
										<Command.Loading>Loading templates...</Command.Loading>
									{:else}
										<Command.Empty>No templates found.</Command.Empty>
									{/if}
									<Command.Group>
										{#each templates as t}
											<Command.Item
												value={t.title}
												onSelect={() => {
													template = t;
													closeAndFocusTrigger();
												}}
											>
												<CheckIcon
													class={cn('me-2 size-4', template !== t && 'text-transparent')}
												/>
												{t.title}
											</Command.Item>
										{/each}
									</Command.Group>
								</Command.List>
							</Command.Root>
						</Popover.Content>
					</Popover.Root>
				</div>
			</div>
			<Dialog.Footer>
				<Dialog.Close type="button" class={buttonVariants({ variant: 'outline' })}>
					Cancel
				</Dialog.Close>
				<Button type="button" onclick={createProtocol}>Save</Button>
			</Dialog.Footer>
		</Dialog.Content>
	</form>
</Dialog.Root>
