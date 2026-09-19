import 'package:flutter/material.dart';
import '../services/api_client.dart';

class NotificationScreen extends StatefulWidget {
  final ApiClient api;
  const NotificationScreen({super.key, required this.api});
  @override
  State<NotificationScreen> createState() => _NotificationScreenState();
}

class _NotificationScreenState extends State<NotificationScreen> {
  late Future<List<dynamic>> _items;
  bool _busy = false;
  @override
  void initState() { super.initState(); _items = widget.api.notificationInbox(); }
  void _reload() { setState(() => _items = widget.api.notificationInbox()); }
  Future<void> _approve(Map<String, dynamic> item, String channel) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final preview = await widget.api.notificationPreview(item['action_id'], channel);
      if (!mounted) return;
      final accepted = await showDialog<bool>(context: context, builder: (context) => AlertDialog(
        title: Text('Approve $channel message'),
        content: SingleChildScrollView(child: Text('To: ${preview['phone']}\n\n${preview['text']}\n\nConfirm that the patient has consented to receive this message on this number. Approval queues delivery; it does not confirm receipt.')),
        actions: [TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Consent confirmed — approve'))],
      ));
      if (accepted != true) return;
      await widget.api.approveNotification(item['action_id'], channel, preview['preview_hash']);
      if (mounted) _reload();
    } catch (error) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$error')));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Patient notifications'), actions: [IconButton(onPressed: _busy ? null : _reload, icon: const Icon(Icons.refresh))]),
    body: FutureBuilder<List<dynamic>>(future: _items, builder: (context, snapshot) {
      if (snapshot.hasError) return const Center(child: Text('Could not load messages. Connect and refresh.'));
      if (!snapshot.hasData) return const Center(child: CircularProgressIndicator());
      if (snapshot.data!.isEmpty) return const Center(child: Text('No patient notifications yet.'));
      return ListView(children: snapshot.data!.map((entry) {
        final item = Map<String, dynamic>.from(entry);
        return Card(child: Padding(padding: const EdgeInsets.all(16), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${item['patient']} — ${item['status']}'), const SizedBox(height: 8), Text(item['content']),
          if (item['status'] == 'draft') Wrap(spacing: 8, children: [
            TextButton(onPressed: _busy ? null : () => _approve(item, 'whatsapp'), child: const Text('Review WhatsApp')),
            TextButton(onPressed: _busy ? null : () => _approve(item, 'sms'), child: const Text('Review SMS')),
          ]),
        ])));
      }).toList());
    }),
  );
}
